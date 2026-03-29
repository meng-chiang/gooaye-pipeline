from __future__ import annotations

import asyncio
import logging
import sys

import structlog

from gooaye.config import get_settings
from gooaye.store import Store

logger = structlog.get_logger()


def _setup_logging() -> None:
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )


def _get_store(settings) -> Store:
    return Store(settings.db_path)


def cli() -> None:
    _setup_logging()
    if len(sys.argv) < 2:
        _print_usage()
        sys.exit(1)

    command = sys.argv[1]

    if command == "run-pipeline":
        _cmd_run_pipeline()
    elif command == "run-stage":
        _cmd_run_stage()
    elif command == "check-new":
        _cmd_check_new()
    elif command == "bot":
        _cmd_bot()
    elif command == "serve":
        _cmd_serve()
    else:
        _print_usage()
        sys.exit(1)


def _print_usage() -> None:
    print(
        "Usage: gooaye <command>\n\n"
        "Commands:\n"
        "  run-pipeline           Run full pipeline for latest unprocessed episode\n"
        "  run-stage <stage> --video-id <id>  Run a single stage\n"
        "  check-new              Check RSS for new episodes\n"
        "  bot                    Start Telegram Bot (polling)\n"
        "  serve                  Start Bot + Scheduler (production)\n"
    )


def _cmd_run_pipeline() -> None:
    import httpx

    from gooaye.crawler import check_new_videos
    from gooaye.pipeline import run_pipeline

    settings = get_settings()
    store = _get_store(settings)

    known = {ep.video_id for ep in store.list_episodes(limit=100)}
    with httpx.Client(timeout=30) as c:
        new_eps = check_new_videos(settings.youtube_channel_id, known, client=c)

    if not new_eps:
        logger.info("No new episodes found.")
        return

    ep = new_eps[0]
    logger.info("Running pipeline", video_id=ep.video_id, title=ep.title)
    asyncio.run(
        run_pipeline(
            ep.video_id,
            ep.canonical_url,
            settings.telegram_chat_id,
            settings=settings,
            store=store,
        )
    )


def _cmd_run_stage() -> None:
    args = sys.argv[2:]
    if len(args) < 3 or args[1] != "--video-id":
        print("Usage: gooaye run-stage <stage> --video-id <id>")
        sys.exit(1)

    stage = args[0]
    video_id = args[2]
    settings = get_settings()
    store = _get_store(settings)

    if stage == "download":
        from gooaye.crawler import download_audio
        path = download_audio(video_id, settings.audio_dir)
        logger.info("Downloaded", path=str(path))

    elif stage == "transcribe":
        from gooaye.transcriber import transcribe_to_file
        audio_path = settings.audio_dir / f"{video_id}.mp3"
        out = transcribe_to_file(audio_path, settings.transcripts_dir, video_id,
                                 model_size=settings.whisper_model_size)
        logger.info("Transcribed", path=str(out))

    elif stage == "analyze":
        from gooaye.analyzer import analyze, save_analysis
        from datetime import datetime, timezone
        transcript = (settings.transcripts_dir / f"{video_id}.txt").read_text("utf-8")
        ep = store.get_episode(video_id)
        analysis = analyze(
            transcript,
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
        save_analysis(analysis, settings.analyses_dir)
        logger.info("Analyzed", video_id=video_id)

    elif stage == "notify":
        import httpx
        from gooaye.notifier import format_analysis_message, send_message
        ep = store.get_episode(video_id)
        if not ep or not ep.analysis_result:
            logger.error("No analysis result found", video_id=video_id)
            sys.exit(1)
        date_str = ep.publish_date.strftime("%Y-%m-%d")
        msg = format_analysis_message(ep.title, date_str, ep.analysis_result)
        with httpx.Client(timeout=30) as c:
            send_message(settings.telegram_chat_id, msg,
                         token=settings.telegram_bot_token, client=c)
        logger.info("Notified", video_id=video_id)
    else:
        print(f"Unknown stage: {stage}")
        sys.exit(1)


def _cmd_check_new() -> None:
    import httpx

    from gooaye.crawler import check_new_videos

    settings = get_settings()
    store = _get_store(settings)
    known = {ep.video_id for ep in store.list_episodes(limit=100)}
    with httpx.Client(timeout=30) as c:
        new_eps = check_new_videos(settings.youtube_channel_id, known, client=c)

    if not new_eps:
        print("No new episodes.")
        return
    for ep in new_eps:
        print(f"  {ep.video_id}  {ep.publish_date.date()}  {ep.title}")


def _log_gpu_status() -> None:
    import ctranslate2
    n = ctranslate2.get_cuda_device_count()
    if n > 0:
        logger.info("GPU detected", cuda_devices=n, whisper_model="large-v3", compute="float16")
    else:
        logger.info("No GPU detected, using CPU", whisper_model="medium", compute="int8")


def _cmd_bot() -> None:
    from gooaye.bot import build_application
    from gooaye.pipeline import run_pipeline

    settings = get_settings()
    store = _get_store(settings)
    _log_gpu_status()

    async def _run_pipeline_wrapper(video_id, url, chat_id):
        await run_pipeline(video_id, url, chat_id, settings=settings, store=store)

    app = build_application(settings, store, _run_pipeline_wrapper)
    logger.info("Starting bot...")
    app.run_polling()


def _cmd_serve() -> None:
    import asyncio

    from gooaye.bot import build_application
    from gooaye.pipeline import check_and_run_new, run_pipeline
    from gooaye.scheduler import build_scheduler

    settings = get_settings()
    store = _get_store(settings)
    _log_gpu_status()

    async def _run_pipeline_wrapper(video_id, url, chat_id):
        await run_pipeline(video_id, url, chat_id, settings=settings, store=store)

    async def _check_and_run():
        await check_and_run_new(settings=settings, store=store)

    scheduler = build_scheduler(settings, _check_and_run)

    app = build_application(settings, store, _run_pipeline_wrapper)

    async def _main():
        scheduler.start()
        logger.info("Scheduler started")
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        logger.info("Bot started. Press Ctrl+C to stop.")
        try:
            await asyncio.Event().wait()
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            logger.info("Shutting down...")
            scheduler.shutdown(wait=False)
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
            logger.info("Stopped.")

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    cli()
