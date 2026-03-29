from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from gooaye.config import Settings, get_settings
from gooaye.models import Analysis, Episode, EpisodeStatus, Transcript


# ── config tests ──────────────────────────────────────────────────────────────

class TestSettings:
    def test_defaults_loaded(self):
        s = Settings()
        assert s.youtube_channel_id == "UC23rnlQU_qE3cec9x709peA"
        assert s.whisper_language == "zh"
        assert s.analyzer_qa_min_position == 0.4
        assert s.data_max_keep_episodes == 20
        assert s.bot_cooldown_seconds == 600

    def test_telegram_allowed_users_parse_string(self):
        s = Settings(telegram_allowed_users="111,222,333")
        assert s.telegram_allowed_users == [111, 222, 333]

    def test_telegram_allowed_users_parse_list(self):
        s = Settings(telegram_allowed_users=[111, 222])
        assert s.telegram_allowed_users == [111, 222]

    def test_telegram_allowed_users_empty(self):
        s = Settings(telegram_allowed_users="")
        assert s.telegram_allowed_users == []

    def test_derived_paths_are_path_objects(self):
        s = Settings()
        assert isinstance(s.data_dir, Path)
        assert isinstance(s.audio_dir, Path)
        assert isinstance(s.transcripts_dir, Path)
        assert isinstance(s.analyses_dir, Path)
        assert isinstance(s.db_path, Path)

    def test_derived_paths_correct_structure(self):
        s = Settings()
        assert s.audio_dir == s.data_dir / "audio"
        assert s.transcripts_dir == s.data_dir / "transcripts"
        assert s.analyses_dir == s.data_dir / "analyses"
        assert s.db_path == s.data_dir / "gooaye.db"

    def test_qa_markers_loaded(self):
        s = Settings()
        assert "Q&A" in s.analyzer_qa_markers
        assert "提問" in s.analyzer_qa_markers

    def test_get_settings_singleton(self):
        import gooaye.config as cfg_module
        cfg_module._settings = None  # reset singleton
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_env_override(self):
        with patch.dict(os.environ, {"GROK_API_KEY": "test-key-123"}):
            s = Settings()
            assert s.grok_api_key == "test-key-123"


# ── models tests ──────────────────────────────────────────────────────────────

class TestEpisode:
    def setup_method(self):
        self.episode = Episode(
            video_id="abc123",
            title="Test Episode",
            publish_date=datetime(2026, 3, 24),
            url="https://www.youtube.com/watch?v=abc123",
        )

    def test_default_status(self):
        assert self.episode.status == EpisodeStatus.PENDING

    def test_canonical_url(self):
        assert self.episode.canonical_url == "https://www.youtube.com/watch?v=abc123"

    def test_created_at_set_automatically(self):
        assert isinstance(self.episode.created_at, datetime)

    def test_status_enum_values(self):
        statuses = [s.value for s in EpisodeStatus]
        assert "pending" in statuses
        assert "done" in statuses
        assert "failed" in statuses


class TestTranscript:
    def test_word_count(self):
        t = Transcript(video_id="abc123", text="這是一段測試文字內容")
        assert t.word_count == len("這是一段測試文字內容")

    def test_default_language(self):
        t = Transcript(video_id="abc123", text="test")
        assert t.language == "zh"

    def test_empty_segments_default(self):
        t = Transcript(video_id="abc123", text="test")
        assert t.segments == []


class TestAnalysis:
    def setup_method(self):
        self.analysis = Analysis(
            video_id="abc123",
            title="Test Episode",
            publish_date=datetime(2026, 3, 24),
            summary="這是摘要內容",
        )

    def test_format_for_telegram_contains_title(self):
        msg = self.analysis.format_for_telegram()
        assert "Test Episode" in msg

    def test_format_for_telegram_contains_date(self):
        msg = self.analysis.format_for_telegram()
        assert "2026-03-24" in msg

    def test_format_for_telegram_contains_summary(self):
        msg = self.analysis.format_for_telegram()
        assert "這是摘要內容" in msg

    def test_created_at_set_automatically(self):
        assert isinstance(self.analysis.created_at, datetime)
