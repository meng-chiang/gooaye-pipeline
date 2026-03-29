from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gooaye.bot import _is_allowed, cmd_help, cmd_latest, cmd_status, cmd_url
from gooaye.models import Episode, EpisodeStatus
from gooaye.store import Store


def _make_update(user_id: int = 1, chat_id: int = 100, args: list[str] | None = None):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = chat_id
    update.message.reply_text = AsyncMock()
    return update


def _make_context(args: list[str] | None = None):
    ctx = MagicMock()
    ctx.args = args or []
    return ctx


def _make_settings(allowed_users: list[int] | None = None, cooldown: int = 600):
    s = MagicMock()
    s.telegram_allowed_users = allowed_users or []
    s.bot_cooldown_seconds = cooldown
    return s


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "test.db")


def _ep(video_id: str = "vid001") -> Episode:
    return Episode(
        video_id=video_id,
        title="Test",
        publish_date=datetime(2026, 3, 24, tzinfo=timezone.utc),
        url=f"https://www.youtube.com/watch?v={video_id}",
    )


# ── _is_allowed ───────────────────────────────────────────────────────────────

class TestIsAllowed:
    def test_empty_allowlist_permits_all(self):
        assert _is_allowed(999, []) is True

    def test_user_in_list_permitted(self):
        assert _is_allowed(42, [42, 99]) is True

    def test_user_not_in_list_blocked(self):
        assert _is_allowed(1, [42, 99]) is False


# ── cmd_help ──────────────────────────────────────────────────────────────────

class TestCmdHelp:
    @pytest.mark.asyncio
    async def test_replies_with_help_text(self):
        update = _make_update()
        await cmd_help(update, _make_context())
        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        assert "/url" in text
        assert "/status" in text
        assert "/latest" in text


# ── cmd_status ────────────────────────────────────────────────────────────────

class TestCmdStatus:
    @pytest.mark.asyncio
    async def test_idle_message_when_no_pipeline(self, store: Store):
        update = _make_update()
        settings = _make_settings()
        await cmd_status(update, _make_context(), store=store, settings=settings)
        text = update.message.reply_text.call_args[0][0]
        assert "閒置" in text

    @pytest.mark.asyncio
    async def test_blocked_when_not_allowed(self, store: Store):
        update = _make_update(user_id=999)
        settings = _make_settings(allowed_users=[42])
        await cmd_status(update, _make_context(), store=store, settings=settings)
        update.message.reply_text.assert_not_called()


# ── cmd_latest ────────────────────────────────────────────────────────────────

class TestCmdLatest:
    @pytest.mark.asyncio
    async def test_no_results_message(self, store: Store):
        update = _make_update()
        settings = _make_settings()
        await cmd_latest(update, _make_context(), store=store, settings=settings)
        text = update.message.reply_text.call_args[0][0]
        assert "尚無" in text

    @pytest.mark.asyncio
    async def test_returns_latest_analysis(self, store: Store):
        ep = _ep()
        store.add_episode(ep)
        store.update_status("vid001", EpisodeStatus.DONE, analysis_result="摘要結果")

        update = _make_update()
        settings = _make_settings()
        await cmd_latest(update, _make_context(), store=store, settings=settings)
        text = update.message.reply_text.call_args[0][0]
        assert "摘要結果" in text

    @pytest.mark.asyncio
    async def test_blocked_when_not_allowed(self, store: Store):
        update = _make_update(user_id=999)
        settings = _make_settings(allowed_users=[42])
        await cmd_latest(update, _make_context(), store=store, settings=settings)
        update.message.reply_text.assert_not_called()


# ── cmd_url ───────────────────────────────────────────────────────────────────

class TestCmdUrl:
    @pytest.mark.asyncio
    async def test_no_args_prompts_usage(self, store: Store):
        update = _make_update()
        settings = _make_settings()
        await cmd_url(update, _make_context(args=[]), store=store,
                      settings=settings, run_pipeline=AsyncMock())
        text = update.message.reply_text.call_args[0][0]
        assert "請提供" in text

    @pytest.mark.asyncio
    async def test_invalid_url_rejected(self, store: Store):
        update = _make_update()
        settings = _make_settings()
        await cmd_url(update, _make_context(args=["https://evil.com/vid"]),
                      store=store, settings=settings, run_pipeline=AsyncMock())
        text = update.message.reply_text.call_args[0][0]
        assert "無效" in text

    @pytest.mark.asyncio
    async def test_blocked_when_not_allowed(self, store: Store):
        update = _make_update(user_id=999)
        settings = _make_settings(allowed_users=[42])
        await cmd_url(
            update,
            _make_context(args=["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]),
            store=store, settings=settings, run_pipeline=AsyncMock(),
        )
        update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_valid_url_sends_processing_message(self, store: Store):
        update = _make_update()
        settings = _make_settings()
        run_pipeline = AsyncMock()

        with patch("gooaye.bot.asyncio.create_task"):
            await cmd_url(
                update,
                _make_context(args=["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]),
                store=store, settings=settings, run_pipeline=run_pipeline,
            )
        text = update.message.reply_text.call_args[0][0]
        assert "⏳" in text
