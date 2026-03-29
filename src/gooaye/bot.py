from __future__ import annotations

import asyncio
import logging
from typing import Callable

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from gooaye.config import Settings
from gooaye.store import Store
from gooaye.validator import InvalidYouTubeURLError, extract_video_id, to_canonical_url

logger = logging.getLogger(__name__)

_pipeline_semaphore = asyncio.Semaphore(1)


def _is_allowed(user_id: int, allowed_users: list[int]) -> bool:
    if not allowed_users:
        return True
    return user_id in allowed_users


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "📖 *使用說明*\n\n"
        "/url <YouTube URL> — 觸發即時下載＋分析\n"
        "/status — 查看目前處理狀態\n"
        "/latest — 取得最近一次分析結果\n"
        "/help — 顯示此說明"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    store: Store,
    settings: Settings,
) -> None:
    user_id = update.effective_user.id
    if not _is_allowed(user_id, settings.telegram_allowed_users):
        return

    busy = _pipeline_semaphore.locked()
    msg = "🔄 目前正在處理中..." if busy else "✅ 閒置中，沒有正在進行的任務。"
    await update.message.reply_text(msg)


async def cmd_latest(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    store: Store,
    settings: Settings,
) -> None:
    user_id = update.effective_user.id
    if not _is_allowed(user_id, settings.telegram_allowed_users):
        return

    episodes = store.list_episodes(limit=1)
    if not episodes or not episodes[0].analysis_result:
        await update.message.reply_text("尚無分析結果。")
        return

    ep = episodes[0]
    date_str = ep.publish_date.strftime("%Y-%m-%d")
    msg = f"📋 最近一次分析結果（{date_str}）：\n\n{ep.analysis_result}"
    await update.message.reply_text(msg)


async def cmd_url(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    store: Store,
    settings: Settings,
    run_pipeline: Callable,
) -> None:
    user_id = update.effective_user.id
    if not _is_allowed(user_id, settings.telegram_allowed_users):
        return

    if not context.args:
        await update.message.reply_text(
            "請提供 YouTube URL，例如: /url https://www.youtube.com/watch?v=xxxxx"
        )
        return

    raw_url = context.args[0]
    try:
        canonical_url = to_canonical_url(raw_url)
        video_id = extract_video_id(raw_url)
    except InvalidYouTubeURLError:
        await update.message.reply_text(
            "❌ 無效的 YouTube URL，請確認格式正確。"
        )
        return

    # Concurrency guard
    if _pipeline_semaphore.locked():
        await update.message.reply_text("⏳ 目前有其他任務正在處理中，請稍後再試。")
        return

    async def _run():
        async with _pipeline_semaphore:
            chat_id = update.effective_chat.id
            await run_pipeline(video_id, canonical_url, chat_id)

    asyncio.create_task(_run())
    await update.message.reply_text("⏳ 開始處理... 下載音訊中")


def build_application(
    settings: Settings,
    store: Store,
    run_pipeline: Callable,
) -> Application:
    app = Application.builder().token(settings.telegram_bot_token).build()

    async def _status(u: Update, c: ContextTypes.DEFAULT_TYPE) -> None:
        await cmd_status(u, c, store=store, settings=settings)

    async def _latest(u: Update, c: ContextTypes.DEFAULT_TYPE) -> None:
        await cmd_latest(u, c, store=store, settings=settings)

    async def _url(u: Update, c: ContextTypes.DEFAULT_TYPE) -> None:
        await cmd_url(u, c, store=store, settings=settings, run_pipeline=run_pipeline)

    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", _status))
    app.add_handler(CommandHandler("latest", _latest))
    app.add_handler(CommandHandler("url", _url))

    return app
