from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Callable

import structlog

import httpx

from gooaye.analyzer import analyze, save_analysis
from gooaye.config import Settings
from gooaye.crawler import check_new_videos, download_audio
from gooaye.models import Episode, EpisodeStatus
from gooaye.notifier import format_analysis_message, send_message, send_progress
from gooaye.store import Store
from gooaye.transcriber import transcribe_to_file
from gooaye.validator import extract_video_id, to_canonical_url

logger = structlog.get_logger(__name__)

ProgressCallback = Callable[[str], None] | None


async def run_pipeline(
    video_id: str,
    url: str,
    chat_id: str | int,
    *,
    settings: Settings,
    store: Store,
) -> None:
    """Full pipeline: download → transcribe → analyze → notify → cleanup."""

    def _notify(msg: str | None = None, *, stage: str | None = None) -> None:
        try:
            with httpx.Client(timeout=10) as c:
                if stage:
                    send_progress(chat_id, stage, token=settings.telegram_bot_token, client=c)
                elif msg:
                    send_message(chat_id, msg, token=settings.telegram_bot_token,
                                 client=c, retries=1)
        except Exception:
            pass

    # Ensure data dirs exist
    settings.audio_dir.mkdir(parents=True, exist_ok=True)
    settings.transcripts_dir.mkdir(parents=True, exist_ok=True)
    settings.analyses_dir.mkdir(parents=True, exist_ok=True)

    # Add episode to store if not present
    episode = store.get_episode(video_id)
    if episode is None:
        episode = Episode(
            video_id=video_id,
            title=video_id,
            publish_date=datetime.now(timezone.utc),
            url=url,
        )
        store.add_episode(episode)

    log = logger.bind(video_id=video_id)
    pipeline_start = time.time()

    try:
        # ── Download ──────────────────────────────────────────────────────────
        store.update_status(video_id, EpisodeStatus.DOWNLOADING)
        _notify(stage="download")

        audio_path = settings.audio_dir / f"{video_id}.mp3"
        if audio_path.exists():
            log.info("audio already exists, skipping download", path=str(audio_path))
        else:
            log.info("downloading audio")
            t0 = time.time()
            await asyncio.to_thread(download_audio, video_id, settings.audio_dir)
            log.info("download complete", elapsed=f"{time.time()-t0:.1f}s",
                     size=f"{audio_path.stat().st_size // 1024 // 1024}MB")

        # ── Transcribe ────────────────────────────────────────────────────────
        store.update_status(video_id, EpisodeStatus.TRANSCRIBING)
        _notify(stage="transcribe")

        transcript_path = settings.transcripts_dir / f"{video_id}.txt"
        if transcript_path.exists():
            log.info("transcript already exists, skipping transcription")
            transcript_text = transcript_path.read_text(encoding="utf-8")
        else:
            log.info("starting transcription", model_size=settings.whisper_model_size)
            t0 = time.time()
            transcript_path = await asyncio.to_thread(
                transcribe_to_file,
                audio_path,
                settings.transcripts_dir,
                video_id,
                model_size=settings.whisper_model_size,
                language=settings.whisper_language,
                initial_prompt=settings.whisper_initial_prompt,
            )
            transcript_text = transcript_path.read_text(encoding="utf-8")
            elapsed = time.time() - t0
            log.info("transcription complete", elapsed=f"{elapsed:.1f}s", chars=len(transcript_text))
            _notify(msg=f"🎙️ 語音轉文字完成（{elapsed/60:.1f} 分鐘），開始 AI 分析...")

        # ── Analyze ───────────────────────────────────────────────────────────
        store.update_status(video_id, EpisodeStatus.ANALYZING)
        _notify(stage="analyze")

        ep = store.get_episode(video_id)
        log.info("starting analysis", model=settings.analyzer_model,
                 transcript_chars=len(transcript_text))
        t0 = time.time()
        analysis = analyze(
            transcript_text,
            video_id=video_id,
            title=ep.title if ep else video_id,
            publish_date=ep.publish_date if ep else datetime.now(timezone.utc),
            prompt_template=settings.analyzer_prompt_template,
            qa_markers=settings.analyzer_qa_markers,
            qa_min_position=settings.analyzer_qa_min_position,
            max_chunk_tokens=settings.analyzer_max_chunk_tokens,
            model=settings.analyzer_model,
            api_key=settings.grok_api_key,
        )
        log.info("analysis complete", elapsed=f"{time.time()-t0:.1f}s")
        save_analysis(analysis, settings.analyses_dir)

        # ── Notify ────────────────────────────────────────────────────────────
        store.update_status(video_id, EpisodeStatus.NOTIFYING,
                            analysis_result=analysis.summary)
        _notify(stage="done")

        date_str = analysis.publish_date.strftime("%Y-%m-%d")
        msg = format_analysis_message(analysis.title, date_str, analysis.summary)
        with httpx.Client(timeout=30) as c:
            send_message(chat_id, msg, token=settings.telegram_bot_token, client=c)

        # ── Done ──────────────────────────────────────────────────────────────
        store.update_status(video_id, EpisodeStatus.DONE,
                            analysis_result=analysis.summary)
        total = time.time() - pipeline_start
        log.info("pipeline complete", total_elapsed=f"{total:.1f}s")

        # ── Cleanup ───────────────────────────────────────────────────────────
        _cleanup(settings)

    except Exception as exc:
        log.exception("pipeline failed", error=str(exc))
        store.update_status(video_id, EpisodeStatus.FAILED,
                            error_message=str(exc))
        _notify(msg=f"❌ 處理 {video_id} 時發生錯誤：{exc}")
        raise


async def check_and_run_new(*, settings: Settings, store: Store) -> None:
    """Scheduler job: check RSS for new episodes and run pipeline for each."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.scheduler_lookback_days)
    known_ids = {ep.video_id for ep in store.list_episodes(limit=100)}
    logger.info("checking RSS", lookback_days=settings.scheduler_lookback_days,
                cutoff=cutoff.strftime("%Y-%m-%d"))
    with httpx.Client(timeout=30) as c:
        new_episodes = check_new_videos(
            settings.youtube_channel_id, known_ids,
            client=c, published_after=cutoff,
        )

    for ep in new_episodes:
        store.add_episode(ep)
        logger.info("New episode found: %s — %s", ep.video_id, ep.title)
        try:
            await run_pipeline(
                ep.video_id,
                ep.canonical_url,
                settings.telegram_chat_id,
                settings=settings,
                store=store,
            )
        except Exception:
            logger.exception("Pipeline failed for scheduled episode %s", ep.video_id)


def _cleanup(settings: Settings) -> None:
    """Remove oldest audio/transcript/analysis files, keeping max_keep_episodes."""
    keep = settings.data_max_keep_episodes
    for directory in (settings.audio_dir, settings.transcripts_dir, settings.analyses_dir):
        files = sorted(directory.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old_file in files[keep:]:
            try:
                old_file.unlink()
            except Exception:
                pass
