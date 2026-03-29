from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from gooaye.models import Episode, EpisodeStatus
from gooaye.pipeline import _cleanup, check_and_run_new, run_pipeline
from gooaye.store import Store

PUBLISH_DATE = datetime(2026, 3, 24, tzinfo=timezone.utc)


def _ep(video_id: str = "vid001") -> Episode:
    return Episode(
        video_id=video_id,
        title="Test Episode",
        publish_date=PUBLISH_DATE,
        url=f"https://www.youtube.com/watch?v={video_id}",
    )


def _make_settings(tmp_path: Path) -> MagicMock:
    s = MagicMock()
    s.audio_dir = tmp_path / "audio"
    s.transcripts_dir = tmp_path / "transcripts"
    s.analyses_dir = tmp_path / "analyses"
    s.whisper_model_size = "medium"
    s.whisper_language = "zh"
    s.whisper_initial_prompt = "以下是繁體中文的內容。"
    s.analyzer_prompt_template = "{transcript}"
    s.analyzer_qa_markers = ["Q&A"]
    s.analyzer_qa_min_position = 0.4
    s.analyzer_max_chunk_tokens = 8000
    s.analyzer_model = "grok-test"
    s.grok_api_key = "test-key"
    s.telegram_bot_token = "bot-token"
    s.telegram_chat_id = "chat-123"
    s.data_max_keep_episodes = 20
    s.scheduler_lookback_days = 4
    return s


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "test.db")


@pytest.fixture
def settings(tmp_path: Path) -> MagicMock:
    return _make_settings(tmp_path)


# ── run_pipeline ──────────────────────────────────────────────────────────────

class TestRunPipeline:
    @pytest.mark.asyncio
    async def test_happy_path_marks_done(self, store: Store, settings: MagicMock, tmp_path: Path):
        store.add_episode(_ep())

        # Pre-create audio + transcript files (simulate prior stages)
        settings.audio_dir.mkdir(parents=True)
        settings.transcripts_dir.mkdir(parents=True)
        settings.analyses_dir.mkdir(parents=True)
        (settings.audio_dir / "vid001.mp3").touch()
        (settings.transcripts_dir / "vid001.txt").write_text("逐字稿內容", encoding="utf-8")

        mock_analysis = MagicMock()
        mock_analysis.summary = "分析摘要"
        mock_analysis.title = "Test Episode"
        mock_analysis.publish_date = PUBLISH_DATE

        with patch("gooaye.pipeline.download_audio"), \
             patch("gooaye.pipeline.transcribe_to_file"), \
             patch("gooaye.pipeline.analyze", return_value=mock_analysis), \
             patch("gooaye.pipeline.save_analysis"), \
             patch("gooaye.pipeline.send_message"), \
             patch("gooaye.pipeline.send_progress"), \
             patch("gooaye.pipeline.httpx.Client"):
            await run_pipeline("vid001", "https://www.youtube.com/watch?v=vid001",
                               "chat-1", settings=settings, store=store)

        ep = store.get_episode("vid001")
        assert ep.status == EpisodeStatus.DONE
        assert ep.analysis_result == "分析摘要"

    @pytest.mark.asyncio
    async def test_failure_marks_failed(self, store: Store, settings: MagicMock):
        store.add_episode(_ep())
        settings.audio_dir.mkdir(parents=True)
        settings.transcripts_dir.mkdir(parents=True)
        settings.analyses_dir.mkdir(parents=True)

        with patch("gooaye.pipeline.download_audio", side_effect=RuntimeError("fail")), \
             patch("gooaye.pipeline.send_message"), \
             patch("gooaye.pipeline.send_progress"), \
             patch("gooaye.pipeline.httpx.Client"), \
             pytest.raises(RuntimeError):
            await run_pipeline("vid001", "https://www.youtube.com/watch?v=vid001",
                               "chat-1", settings=settings, store=store)

        ep = store.get_episode("vid001")
        assert ep.status == EpisodeStatus.FAILED
        assert "fail" in ep.error_message

    @pytest.mark.asyncio
    async def test_skips_download_if_audio_exists(self, store: Store, settings: MagicMock):
        store.add_episode(_ep())
        settings.audio_dir.mkdir(parents=True)
        settings.transcripts_dir.mkdir(parents=True)
        settings.analyses_dir.mkdir(parents=True)
        (settings.audio_dir / "vid001.mp3").touch()
        (settings.transcripts_dir / "vid001.txt").write_text("text", encoding="utf-8")

        mock_analysis = MagicMock()
        mock_analysis.summary = "ok"
        mock_analysis.title = "T"
        mock_analysis.publish_date = PUBLISH_DATE

        with patch("gooaye.pipeline.download_audio") as mock_dl, \
             patch("gooaye.pipeline.transcribe_to_file"), \
             patch("gooaye.pipeline.analyze", return_value=mock_analysis), \
             patch("gooaye.pipeline.save_analysis"), \
             patch("gooaye.pipeline.send_message"), \
             patch("gooaye.pipeline.send_progress"), \
             patch("gooaye.pipeline.httpx.Client"):
            await run_pipeline("vid001", "https://www.youtube.com/watch?v=vid001",
                               "chat-1", settings=settings, store=store)

        mock_dl.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_episode_if_not_in_store(self, store: Store, settings: MagicMock):
        settings.audio_dir.mkdir(parents=True)
        settings.transcripts_dir.mkdir(parents=True)
        settings.analyses_dir.mkdir(parents=True)
        (settings.audio_dir / "vid999.mp3").touch()
        (settings.transcripts_dir / "vid999.txt").write_text("text", encoding="utf-8")

        mock_analysis = MagicMock()
        mock_analysis.summary = "ok"
        mock_analysis.title = "T"
        mock_analysis.publish_date = PUBLISH_DATE

        with patch("gooaye.pipeline.download_audio"), \
             patch("gooaye.pipeline.transcribe_to_file"), \
             patch("gooaye.pipeline.analyze", return_value=mock_analysis), \
             patch("gooaye.pipeline.save_analysis"), \
             patch("gooaye.pipeline.send_message"), \
             patch("gooaye.pipeline.send_progress"), \
             patch("gooaye.pipeline.httpx.Client"):
            await run_pipeline("vid999", "https://www.youtube.com/watch?v=vid999",
                               "chat-1", settings=settings, store=store)

        ep = store.get_episode("vid999")
        assert ep is not None


# ── check_and_run_new ─────────────────────────────────────────────────────────

class TestCheckAndRunNew:
    @pytest.mark.asyncio
    async def test_runs_pipeline_for_new_episodes(self, store: Store, settings: MagicMock):
        new_ep = _ep("newvid01")

        with patch("gooaye.pipeline.check_new_videos", return_value=[new_ep]), \
             patch("gooaye.pipeline.httpx.Client"), \
             patch("gooaye.pipeline.run_pipeline", new_callable=AsyncMock) as mock_run:
            await check_and_run_new(settings=settings, store=store)

        mock_run.assert_called_once_with(
            "newvid01",
            new_ep.canonical_url,
            settings.telegram_chat_id,
            settings=settings,
            store=store,
        )

    @pytest.mark.asyncio
    async def test_skips_known_episodes(self, store: Store, settings: MagicMock):
        with patch("gooaye.pipeline.check_new_videos", return_value=[]), \
             patch("gooaye.pipeline.httpx.Client"), \
             patch("gooaye.pipeline.run_pipeline", new_callable=AsyncMock) as mock_run:
            await check_and_run_new(settings=settings, store=store)

        mock_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_continues_on_pipeline_error(self, store: Store, settings: MagicMock):
        ep1 = _ep("vid001")
        ep2 = _ep("vid002")

        with patch("gooaye.pipeline.check_new_videos", return_value=[ep1, ep2]), \
             patch("gooaye.pipeline.httpx.Client"), \
             patch("gooaye.pipeline.run_pipeline", new_callable=AsyncMock,
                   side_effect=[RuntimeError("fail"), None]) as mock_run:
            await check_and_run_new(settings=settings, store=store)

        assert mock_run.call_count == 2


# ── _cleanup ──────────────────────────────────────────────────────────────────

class TestCleanup:
    def test_removes_old_files(self, tmp_path: Path):
        settings = _make_settings(tmp_path)
        settings.audio_dir.mkdir(parents=True)
        settings.transcripts_dir.mkdir(parents=True)
        settings.analyses_dir.mkdir(parents=True)
        settings.data_max_keep_episodes = 2

        for i in range(5):
            f = settings.audio_dir / f"vid{i:03}.mp3"
            f.touch()
            import time; time.sleep(0.01)  # ensure mtime differs

        _cleanup(settings)
        remaining = list(settings.audio_dir.glob("*.mp3"))
        assert len(remaining) == 2

    def test_does_nothing_within_keep_limit(self, tmp_path: Path):
        settings = _make_settings(tmp_path)
        settings.audio_dir.mkdir(parents=True)
        settings.transcripts_dir.mkdir(parents=True)
        settings.analyses_dir.mkdir(parents=True)
        settings.data_max_keep_episodes = 20

        for i in range(3):
            (settings.audio_dir / f"vid{i:03}.mp3").touch()

        _cleanup(settings)
        assert len(list(settings.audio_dir.glob("*.mp3"))) == 3
