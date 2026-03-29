from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import tiktoken
from openai import OpenAI

from gooaye.models import Analysis

_ENC = tiktoken.get_encoding("cl100k_base")


def _token_count(text: str) -> int:
    return len(_ENC.encode(text))


def trim_qa_section(
    text: str,
    qa_markers: list[str],
    qa_min_position: float = 0.4,
) -> str:
    """Remove Q&A section from transcript.

    Returns text up to the first QA marker that appears after qa_min_position
    of the total text. If no valid marker is found, returns the full text.
    """
    lower = text.lower()
    total = len(text)
    best_pos = -1

    for marker in qa_markers:
        idx = lower.find(marker.lower())
        while idx != -1:
            if idx / total >= qa_min_position:
                if best_pos == -1 or idx < best_pos:
                    best_pos = idx
                break
            idx = lower.find(marker.lower(), idx + 1)

    if best_pos == -1:
        return text
    return text[:best_pos].strip()


def _chunk_text(text: str, max_tokens: int) -> list[str]:
    """Split text into chunks of at most max_tokens, breaking at paragraph boundaries."""
    paragraphs = [p for p in text.split("\n") if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for para in paragraphs:
        para_tokens = _token_count(para)
        if current_tokens + para_tokens > max_tokens and current:
            chunks.append("\n".join(current))
            current = []
            current_tokens = 0
        current.append(para)
        current_tokens += para_tokens

    if current:
        chunks.append("\n".join(current))
    return chunks


def _call_api(
    client: OpenAI,
    model: str,
    prompt: str,
    *,
    retries: int = 3,
) -> str:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.choices[0].message.content or ""
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Grok API failed after {retries} attempts") from last_exc


def analyze(
    transcript: str,
    *,
    video_id: str,
    title: str,
    publish_date: datetime,
    prompt_template: str,
    qa_markers: list[str],
    qa_min_position: float = 0.4,
    max_chunk_tokens: int = 8000,
    model: str = "grok-4-1-fast-non-reasoning",
    api_key: str,
    retries: int = 3,
) -> Analysis:
    """Full analysis pipeline: trim Q&A → chunk → summarize → merge."""
    client = OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")

    trimmed = trim_qa_section(transcript, qa_markers, qa_min_position)
    chunks = _chunk_text(trimmed, max_chunk_tokens)

    if len(chunks) == 1:
        prompt = prompt_template.format(transcript=chunks[0])
        summary = _call_api(client, model, prompt, retries=retries)
    else:
        chunk_summaries: list[str] = []
        for i, chunk in enumerate(chunks, 1):
            chunk_prompt = (
                f"以下是 Podcast 逐字稿的第 {i}/{len(chunks)} 部分，"
                f"請摘要這部分的重點：\n\n{chunk}"
            )
            chunk_summaries.append(
                _call_api(client, model, chunk_prompt, retries=retries)
            )
        merge_prompt = (
            f"以下是同一集 Podcast 各段落的摘要，請整合成最終完整摘要：\n\n"
            + "\n\n---\n\n".join(chunk_summaries)
        )
        summary = _call_api(client, model, merge_prompt, retries=retries)

    return Analysis(
        video_id=video_id,
        title=title,
        publish_date=publish_date,
        summary=summary,
        raw_transcript_trimmed=trimmed,
        model_used=model,
    )


def save_analysis(analysis: Analysis, output_dir: Path) -> Path:
    """Serialize Analysis to JSON and save to output_dir/{video_id}.json."""
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{analysis.video_id}.json"
    data = {
        "video_id": analysis.video_id,
        "title": analysis.title,
        "publish_date": analysis.publish_date.isoformat(),
        "summary": analysis.summary,
        "raw_transcript_trimmed": analysis.raw_transcript_trimmed,
        "model_used": analysis.model_used,
        "created_at": analysis.created_at.isoformat(),
    }
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path
