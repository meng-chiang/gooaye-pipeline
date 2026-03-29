from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from gooaye.analyzer import (
    _call_api,
    _chunk_text,
    _token_count,
    analyze,
    save_analysis,
    trim_qa_section,
)
from gooaye.models import Analysis

QA_MARKERS = ["Q&A", "提問", "聽眾問題", "來看一下問題", "觀眾提問"]
PUBLISH_DATE = datetime(2026, 3, 24, tzinfo=timezone.utc)


# ── trim_qa_section ───────────────────────────────────────────────────────────

class TestTrimQaSection:
    def test_trims_at_qa_marker(self):
        text = "A" * 100 + "Q&A" + "B" * 100
        result = trim_qa_section(text, QA_MARKERS, qa_min_position=0.4)
        assert "B" not in result
        assert result == "A" * 100

    def test_ignores_marker_before_min_position(self):
        # marker at 10% position — should be ignored
        text = "Q&A" + "A" * 200
        result = trim_qa_section(text, QA_MARKERS, qa_min_position=0.4)
        assert result == text

    def test_returns_full_text_when_no_marker(self):
        text = "只有正文內容，沒有問答段落。" * 10
        result = trim_qa_section(text, QA_MARKERS, qa_min_position=0.4)
        assert result == text

    def test_case_insensitive_marker(self):
        text = "A" * 100 + "q&a" + "B" * 100
        result = trim_qa_section(text, QA_MARKERS, qa_min_position=0.4)
        assert "B" not in result

    def test_picks_earliest_valid_marker(self):
        # two markers — should cut at the earlier one
        text = "A" * 80 + "提問" + "middle" * 5 + "Q&A" + "end" * 10
        result = trim_qa_section(text, QA_MARKERS, qa_min_position=0.4)
        assert "end" not in result
        assert "middle" not in result

    def test_empty_text_returns_empty(self):
        assert trim_qa_section("", QA_MARKERS) == ""

    def test_strips_trailing_whitespace(self):
        text = "Content   \n" * 50 + "Q&A" + "noise"
        result = trim_qa_section(text, QA_MARKERS, qa_min_position=0.4)
        assert not result.endswith(" ")


# ── _chunk_text ───────────────────────────────────────────────────────────────

class TestChunkText:
    def test_single_chunk_when_under_limit(self):
        text = "短文字\n" * 5
        chunks = _chunk_text(text, max_tokens=10000)
        assert len(chunks) == 1

    def test_splits_into_multiple_chunks(self):
        # Each line ~5 tokens; 10 lines = ~50 tokens; limit 20 → should split
        lines = [f"這是第{i}行的測試內容文字段落。" for i in range(20)]
        text = "\n".join(lines)
        chunks = _chunk_text(text, max_tokens=20)
        assert len(chunks) > 1

    def test_no_chunk_exceeds_token_limit_by_paragraph(self):
        lines = ["短行"] * 30
        text = "\n".join(lines)
        chunks = _chunk_text(text, max_tokens=10)
        # Each chunk should start fresh; token count per chunk ≤ limit
        for chunk in chunks:
            assert _token_count(chunk) <= 10 * 2  # some tolerance for single large lines

    def test_empty_text_returns_empty_list(self):
        assert _chunk_text("", max_tokens=1000) == []

    def test_reassembled_chunks_contain_all_content(self):
        lines = [f"paragraph_{i}" for i in range(10)]
        text = "\n".join(lines)
        chunks = _chunk_text(text, max_tokens=5)
        reassembled = "\n".join(chunks)
        for line in lines:
            assert line in reassembled


# ── _call_api ─────────────────────────────────────────────────────────────────

class TestCallApi:
    def _mock_client(self, content: str) -> MagicMock:
        client = MagicMock()
        resp = MagicMock()
        resp.choices[0].message.content = content
        client.chat.completions.create.return_value = resp
        return client

    def test_returns_response_content(self):
        client = self._mock_client("分析結果")
        result = _call_api(client, "grok-model", "prompt")
        assert result == "分析結果"

    def test_retries_on_failure(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            Exception("timeout"),
            Exception("timeout"),
            MagicMock(choices=[MagicMock(message=MagicMock(content="成功"))]),
        ]
        with patch("gooaye.analyzer.time.sleep"):
            result = _call_api(client, "model", "prompt", retries=3)
        assert result == "成功"
        assert client.chat.completions.create.call_count == 3

    def test_raises_after_all_retries_fail(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = Exception("fail")
        with patch("gooaye.analyzer.time.sleep"), pytest.raises(RuntimeError, match="Grok API failed"):
            _call_api(client, "model", "prompt", retries=2)


# ── analyze ───────────────────────────────────────────────────────────────────

class TestAnalyze:
    def _common_kwargs(self, api_key: str = "key") -> dict:
        return dict(
            video_id="vid001",
            title="Test Episode",
            publish_date=PUBLISH_DATE,
            prompt_template="分析以下內容：\n{transcript}",
            qa_markers=QA_MARKERS,
            qa_min_position=0.4,
            max_chunk_tokens=8000,
            model="grok-test-model",
            api_key=api_key,
        )

    def test_returns_analysis_object(self):
        with patch("gooaye.analyzer.OpenAI") as mock_openai_cls:
            client = MagicMock()
            resp = MagicMock()
            resp.choices[0].message.content = "摘要結果"
            client.chat.completions.create.return_value = resp
            mock_openai_cls.return_value = client

            result = analyze("短文字內容。" * 10, **self._common_kwargs())

        assert isinstance(result, Analysis)
        assert result.summary == "摘要結果"
        assert result.video_id == "vid001"

    def test_trims_qa_before_analysis(self):
        transcript = "正文內容。" * 50 + "Q&A" + "問答內容。" * 20
        with patch("gooaye.analyzer.OpenAI") as mock_openai_cls:
            client = MagicMock()
            resp = MagicMock()
            resp.choices[0].message.content = "ok"
            client.chat.completions.create.return_value = resp
            mock_openai_cls.return_value = client

            result = analyze(transcript, **self._common_kwargs())

        assert "問答內容" not in result.raw_transcript_trimmed

    def test_merges_multiple_chunks(self):
        # Use tiny chunk size to force chunking
        long_text = "這是一段很長的測試文字內容。\n" * 200
        with patch("gooaye.analyzer.OpenAI") as mock_openai_cls:
            client = MagicMock()
            resp = MagicMock()
            resp.choices[0].message.content = "chunk summary"
            client.chat.completions.create.return_value = resp
            mock_openai_cls.return_value = client

            kwargs = self._common_kwargs()
            kwargs["max_chunk_tokens"] = 20
            result = analyze(long_text, **kwargs)

        # Should have been called more than once (chunks + merge)
        assert client.chat.completions.create.call_count > 1
        assert isinstance(result, Analysis)

    def test_uses_grok_base_url(self):
        with patch("gooaye.analyzer.OpenAI") as mock_openai_cls:
            client = MagicMock()
            resp = MagicMock()
            resp.choices[0].message.content = "ok"
            client.chat.completions.create.return_value = resp
            mock_openai_cls.return_value = client

            analyze("content", **self._common_kwargs(api_key="test-key"))

        mock_openai_cls.assert_called_once_with(
            api_key="test-key", base_url="https://api.x.ai/v1"
        )


# ── save_analysis ─────────────────────────────────────────────────────────────

class TestSaveAnalysis:
    def test_creates_json_file(self, tmp_path: Path):
        a = Analysis(
            video_id="vid001",
            title="Test",
            publish_date=PUBLISH_DATE,
            summary="摘要",
        )
        out = save_analysis(a, tmp_path)
        assert out.exists()
        assert out.suffix == ".json"

    def test_json_content_correct(self, tmp_path: Path):
        a = Analysis(
            video_id="vid001",
            title="Test",
            publish_date=PUBLISH_DATE,
            summary="摘要內容",
            model_used="grok-model",
        )
        out = save_analysis(a, tmp_path)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["video_id"] == "vid001"
        assert data["summary"] == "摘要內容"
        assert data["model_used"] == "grok-model"

    def test_filename_uses_video_id(self, tmp_path: Path):
        a = Analysis(
            video_id="myVid123",
            title="T",
            publish_date=PUBLISH_DATE,
            summary="s",
        )
        out = save_analysis(a, tmp_path)
        assert out.name == "myVid123.json"

    def test_creates_output_dir(self, tmp_path: Path):
        nested = tmp_path / "a" / "b"
        a = Analysis(video_id="v", title="T", publish_date=PUBLISH_DATE, summary="s")
        save_analysis(a, nested)
        assert nested.exists()
