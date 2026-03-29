from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import httpx
import pytest

from gooaye.notifier import (
    _split_message,
    format_analysis_message,
    send_message,
    send_progress,
)

TOKEN = "bot-token-123"
CHAT_ID = "12345"


# ── _split_message ────────────────────────────────────────────────────────────

class TestSplitMessage:
    def test_short_message_not_split(self):
        text = "Hello world"
        assert _split_message(text) == [text]

    def test_exact_max_length_not_split(self):
        text = "A" * 4096
        assert _split_message(text) == [text]

    def test_long_message_split(self):
        # Create a text > 4096 chars using paragraphs
        paragraphs = ["A" * 100] * 50  # 5000+ chars
        text = "\n".join(paragraphs)
        parts = _split_message(text)
        assert len(parts) > 1

    def test_each_part_within_limit(self):
        paragraphs = ["B" * 200] * 30
        text = "\n".join(paragraphs)
        parts = _split_message(text, max_length=1000)
        for part in parts:
            assert len(part) <= 1000

    def test_reassembled_content_complete(self):
        paragraphs = [f"paragraph_{i}" for i in range(50)]
        text = "\n".join(paragraphs)
        parts = _split_message(text, max_length=500)
        reassembled = "\n".join(parts)
        for p in paragraphs:
            assert p in reassembled

    def test_empty_string(self):
        assert _split_message("") == [""]


# ── send_message ──────────────────────────────────────────────────────────────

class TestSendMessage:
    def _mock_client(self) -> MagicMock:
        client = MagicMock(spec=httpx.Client)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        client.post.return_value = resp
        return client

    def test_posts_to_telegram_api(self):
        client = self._mock_client()
        send_message(CHAT_ID, "Hello", token=TOKEN, client=client)
        client.post.assert_called_once()
        url = client.post.call_args[0][0]
        assert TOKEN in url

    def test_sends_correct_payload(self):
        client = self._mock_client()
        send_message(CHAT_ID, "Test message", token=TOKEN, client=client)
        payload = client.post.call_args[1]["json"]
        assert payload["chat_id"] == CHAT_ID
        assert payload["text"] == "Test message"
        assert payload["parse_mode"] == "Markdown"

    def test_long_message_sent_in_parts(self):
        client = self._mock_client()
        paragraphs = ["X" * 200] * 30  # forces split
        text = "\n".join(paragraphs)
        send_message(CHAT_ID, text, token=TOKEN, client=client, retries=1)
        assert client.post.call_count > 1

    def test_retries_on_http_error(self):
        client = MagicMock(spec=httpx.Client)
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )
        client.post.return_value = resp

        with patch("gooaye.notifier.time.sleep"), pytest.raises(RuntimeError, match="Telegram send failed"):
            send_message(CHAT_ID, "msg", token=TOKEN, retries=2, client=client)

        assert client.post.call_count == 2

    def test_raises_after_all_retries(self):
        client = MagicMock(spec=httpx.Client)
        client.post.side_effect = Exception("network error")

        with patch("gooaye.notifier.time.sleep"), pytest.raises(RuntimeError):
            send_message(CHAT_ID, "msg", token=TOKEN, retries=3, client=client)

        assert client.post.call_count == 3


# ── send_progress ─────────────────────────────────────────────────────────────

class TestSendProgress:
    def test_sends_download_stage(self):
        client = MagicMock(spec=httpx.Client)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        client.post.return_value = resp

        send_progress(CHAT_ID, "download", token=TOKEN, client=client)
        client.post.assert_called_once()
        payload = client.post.call_args[1]["json"]
        assert "下載" in payload["text"]

    def test_sends_done_stage(self):
        client = MagicMock(spec=httpx.Client)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        client.post.return_value = resp

        send_progress(CHAT_ID, "done", token=TOKEN, client=client)
        payload = client.post.call_args[1]["json"]
        assert "✅" in payload["text"]

    def test_swallows_error(self):
        client = MagicMock(spec=httpx.Client)
        client.post.side_effect = Exception("network down")
        # Should not raise
        send_progress(CHAT_ID, "analyze", token=TOKEN, client=client)

    def test_unknown_stage_sends_generic_message(self):
        client = MagicMock(spec=httpx.Client)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        client.post.return_value = resp

        send_progress(CHAT_ID, "unknown_stage", token=TOKEN, client=client)
        payload = client.post.call_args[1]["json"]
        assert "unknown_stage" in payload["text"]


# ── format_analysis_message ───────────────────────────────────────────────────

class TestFormatAnalysisMessage:
    def test_contains_title(self):
        msg = format_analysis_message("Test Title", "2026-03-24", "Summary")
        assert "Test Title" in msg

    def test_contains_date(self):
        msg = format_analysis_message("Title", "2026-03-24", "Summary")
        assert "2026-03-24" in msg

    def test_contains_summary(self):
        msg = format_analysis_message("Title", "2026-03-24", "重要摘要內容")
        assert "重要摘要內容" in msg

    def test_uses_markdown_bold_for_title(self):
        msg = format_analysis_message("Title", "date", "sum")
        assert "*Title*" in msg
