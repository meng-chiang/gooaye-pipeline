from __future__ import annotations

import time

import httpx

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_MAX_LENGTH = 4096


def _split_message(text: str, max_length: int = _MAX_LENGTH) -> list[str]:
    """Split text at paragraph boundaries, keeping each part ≤ max_length."""
    if len(text) <= max_length:
        return [text]

    parts: list[str] = []
    paragraphs = text.split("\n")
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        # +1 for the newline separator
        add_len = len(para) + (1 if current else 0)
        if current_len + add_len > max_length and current:
            parts.append("\n".join(current))
            current = []
            current_len = 0
        current.append(para)
        current_len += add_len

    if current:
        parts.append("\n".join(current))
    return parts


def send_message(
    chat_id: str | int,
    text: str,
    *,
    token: str,
    parse_mode: str = "Markdown",
    retries: int = 3,
    client: httpx.Client | None = None,
) -> None:
    """Send a Telegram message, splitting if > 4096 chars."""
    parts = _split_message(text)
    _client = client or httpx.Client(timeout=30)
    try:
        for part in parts:
            _send_one(chat_id, part, token=token, parse_mode=parse_mode,
                      retries=retries, client=_client)
    finally:
        if client is None:
            _client.close()


def _send_one(
    chat_id: str | int,
    text: str,
    *,
    token: str,
    parse_mode: str,
    retries: int,
    client: httpx.Client,
) -> None:
    url = _TELEGRAM_API.format(token=token)
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            return
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Telegram send failed after {retries} attempts") from last_exc


def send_progress(
    chat_id: str | int,
    stage: str,
    *,
    token: str,
    client: httpx.Client | None = None,
) -> None:
    """Send a short progress update. Swallows errors (best-effort)."""
    _STAGE_MESSAGES = {
        "download": "⏳ 開始處理... 下載音訊中",
        "transcribe": "🎙️ 語音轉文字中（約需 5-10 分鐘）",
        "analyze": "🔍 AI 分析中...",
        "done": "✅ 分析完成！",
        "error": "❌ 處理時發生錯誤，請稍後再試。",
    }
    msg = _STAGE_MESSAGES.get(stage, f"⏳ {stage}")
    try:
        send_message(chat_id, msg, token=token, retries=1, client=client)
    except Exception:
        pass


def format_analysis_message(title: str, date_str: str, summary: str) -> str:
    """Format analysis result for Telegram."""
    return f"📊 *{title}*\n📅 {date_str}\n\n{summary}"
