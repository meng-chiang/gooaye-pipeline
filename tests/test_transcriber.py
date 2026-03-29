from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import gooaye.transcriber as transcriber_module
from gooaye.transcriber import (
    _detect_device,
    _get_model,
    _s2t,
    reset_model,
    transcribe,
    transcribe_to_file,
)


@pytest.fixture(autouse=True)
def reset_singleton():
    """Ensure the model singleton is cleared before each test."""
    reset_model()
    yield
    reset_model()


# ── s2t (opencc) ──────────────────────────────────────────────────────────────

class TestS2T:
    def test_converts_simplified_to_traditional(self):
        result = _s2t("这是简体中文")
        assert "這" in result or "這是" in result  # 这→這

    def test_traditional_unchanged(self):
        text = "這是繁體中文，不需要轉換。"
        assert _s2t(text) == text

    def test_mixed_converts_simplified_parts(self):
        result = _s2t("台湾的繁体")
        assert "灣" in result  # 湾→灣


# ── _detect_device ────────────────────────────────────────────────────────────

class TestDetectDevice:
    def test_returns_large_v3_with_cuda(self):
        with patch("gooaye.transcriber.ctranslate2.get_cuda_device_count", return_value=1):
            size, device, compute = _detect_device()
        assert size == "large-v3"
        assert device == "cuda"
        assert compute == "float16"

    def test_returns_medium_without_cuda(self):
        with patch("gooaye.transcriber.ctranslate2.get_cuda_device_count", return_value=0):
            size, device, compute = _detect_device()
        assert size == "medium"
        assert device == "cpu"
        assert compute == "int8"


# ── _get_model singleton ──────────────────────────────────────────────────────

class TestGetModel:
    def test_returns_same_instance_on_second_call(self):
        mock_model = MagicMock()
        with patch("gooaye.transcriber.WhisperModel", return_value=mock_model) as mock_cls:
            m1 = _get_model("medium")
            m2 = _get_model("medium")
        assert m1 is m2
        assert mock_cls.call_count == 1

    def test_reset_allows_reload(self):
        mock_model = MagicMock()
        with patch("gooaye.transcriber.WhisperModel", return_value=mock_model) as mock_cls:
            _get_model("medium")
            reset_model()
            _get_model("medium")
        assert mock_cls.call_count == 2


# ── transcribe ────────────────────────────────────────────────────────────────

def _make_segment(text: str):
    seg = MagicMock()
    seg.text = text
    return seg


class TestTranscribe:
    def _setup_mock_model(self, segments: list[str]):
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (
            [_make_segment(t) for t in segments],
            MagicMock(),
        )
        transcriber_module._model_instance = mock_model
        return mock_model

    def test_concatenates_segments(self, tmp_path: Path):
        audio = tmp_path / "audio.mp3"
        audio.touch()
        self._setup_mock_model(["第一段", "第二段", "第三段"])
        result = transcribe(audio)
        assert "第一段" in result
        assert "第二段" in result

    def test_skips_empty_segments(self, tmp_path: Path):
        audio = tmp_path / "audio.mp3"
        audio.touch()
        self._setup_mock_model(["有內容", "", "   ", "也有內容"])
        result = transcribe(audio)
        lines = [l for l in result.splitlines() if l]
        assert len(lines) == 2

    def test_applies_s2t_conversion(self, tmp_path: Path):
        audio = tmp_path / "audio.mp3"
        audio.touch()
        self._setup_mock_model(["这是简体"])
        with patch("gooaye.transcriber._s2t", return_value="這是繁體") as mock_s2t:
            result = transcribe(audio)
        mock_s2t.assert_called_once()
        assert result == "這是繁體"

    def test_passes_language_and_prompt(self, tmp_path: Path):
        audio = tmp_path / "audio.mp3"
        audio.touch()
        mock_model = self._setup_mock_model(["text"])
        transcribe(audio, language="zh", initial_prompt="hint")
        mock_model.transcribe.assert_called_once_with(
            str(audio), language="zh", initial_prompt="hint", beam_size=5
        )


# ── transcribe_to_file ────────────────────────────────────────────────────────

class TestTranscribeToFile:
    def test_writes_text_file(self, tmp_path: Path):
        audio = tmp_path / "audio.mp3"
        audio.touch()
        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([_make_segment("測試內容")], MagicMock())
        transcriber_module._model_instance = mock_model

        out = transcribe_to_file(audio, tmp_path / "transcripts", "vid001")
        assert out.exists()
        assert out.read_text(encoding="utf-8") != ""

    def test_output_filename_uses_video_id(self, tmp_path: Path):
        audio = tmp_path / "audio.mp3"
        audio.touch()
        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([_make_segment("text")], MagicMock())
        transcriber_module._model_instance = mock_model

        out = transcribe_to_file(audio, tmp_path, "myVideoId")
        assert out.name == "myVideoId.txt"

    def test_creates_output_dir(self, tmp_path: Path):
        audio = tmp_path / "audio.mp3"
        audio.touch()
        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([_make_segment("text")], MagicMock())
        transcriber_module._model_instance = mock_model

        nested = tmp_path / "a" / "b" / "transcripts"
        transcribe_to_file(audio, nested, "vid001")
        assert nested.exists()
