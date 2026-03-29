from __future__ import annotations

import logging
from pathlib import Path

import ctranslate2
import opencc
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

_model_instance: WhisperModel | None = None
_opencc_converter = opencc.OpenCC("s2t")


def _detect_device() -> tuple[str, str, str]:
    """Return (model_size, device, compute_type) based on hardware availability.

    Verifies CUDA runtime is actually loadable before committing to GPU mode.
    Falls back to CPU if GPU is detected but runtime libraries are missing.
    """
    if ctranslate2.get_cuda_device_count() > 0:
        try:
            # Verify CUDA runtime loads without error
            ctranslate2.get_supported_compute_types("cuda")
            return "large-v3", "cuda", "float16"
        except RuntimeError as e:
            logger.warning("GPU detected but CUDA runtime unavailable, falling back to CPU: %s", e)
    return "medium", "cpu", "int8"


def _get_model(model_size: str = "auto") -> WhisperModel:
    """Return a singleton WhisperModel, loading it on first call."""
    global _model_instance
    if _model_instance is not None:
        return _model_instance

    if model_size == "auto":
        size, device, compute_type = _detect_device()
    else:
        size = model_size
        device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"

    logger.info(
        "Loading Whisper model: size=%s device=%s compute_type=%s",
        size, device, compute_type,
    )
    _model_instance = WhisperModel(size, device=device, compute_type=compute_type)
    logger.info("Whisper model loaded")
    return _model_instance


def reset_model() -> None:
    """Release the singleton model (for testing)."""
    global _model_instance
    _model_instance = None


def _s2t(text: str) -> str:
    return _opencc_converter.convert(text)


def transcribe(
    audio_path: Path,
    *,
    model_size: str = "auto",
    language: str = "zh",
    initial_prompt: str = "以下是繁體中文的內容。",
) -> str:
    """Transcribe audio file to text, returning Traditional Chinese string.

    Segments are concatenated with newlines. Simplified Chinese is converted
    to Traditional Chinese via opencc.
    """
    model = _get_model(model_size)
    segments, _info = model.transcribe(
        str(audio_path),
        language=language,
        initial_prompt=initial_prompt,
        beam_size=5,
    )

    raw_text = "\n".join(seg.text.strip() for seg in segments if seg.text.strip())
    return _s2t(raw_text)


def transcribe_to_file(
    audio_path: Path,
    output_dir: Path,
    video_id: str,
    *,
    model_size: str = "auto",
    language: str = "zh",
    initial_prompt: str = "以下是繁體中文的內容。",
) -> Path:
    """Transcribe audio and save result to output_dir/{video_id}.txt."""
    output_dir.mkdir(parents=True, exist_ok=True)
    text = transcribe(
        audio_path,
        model_size=model_size,
        language=language,
        initial_prompt=initial_prompt,
    )
    out_path = output_dir / f"{video_id}.txt"
    out_path.write_text(text, encoding="utf-8")
    return out_path
