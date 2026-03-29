from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).parent.parent.parent
_SETTINGS_PATH = _ROOT / "config" / "settings.yaml"


def _load_yaml() -> dict[str, Any]:
    if _SETTINGS_PATH.exists():
        with open(_SETTINGS_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}


_yaml = _load_yaml()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    # Secrets from .env
    grok_api_key: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_allowed_users: list[int] = []

    # From settings.yaml (with defaults)
    youtube_channel_id: str = _yaml.get("youtube", {}).get(
        "channel_id", "UC23rnlQU_qE3cec9x709peA"
    )

    whisper_model_size: str = _yaml.get("whisper", {}).get("model_size", "auto")
    whisper_language: str = _yaml.get("whisper", {}).get("language", "zh")
    whisper_initial_prompt: str = _yaml.get("whisper", {}).get(
        "initial_prompt", "以下是繁體中文的內容。"
    )

    analyzer_model: str = _yaml.get("analyzer", {}).get(
        "model", "grok-4-1-fast-non-reasoning"
    )
    analyzer_max_chunk_tokens: int = _yaml.get("analyzer", {}).get(
        "max_chunk_tokens", 8000
    )
    analyzer_prompt_template: str = _yaml.get("analyzer", {}).get(
        "prompt_template", "{transcript}"
    )
    analyzer_qa_markers: list[str] = _yaml.get("analyzer", {}).get(
        "qa_markers", ["Q&A", "提問", "聽眾問題"]
    )
    analyzer_qa_min_position: float = _yaml.get("analyzer", {}).get(
        "qa_min_position", 0.4
    )

    data_max_keep_episodes: int = _yaml.get("data", {}).get("max_keep_episodes", 20)

    bot_cooldown_seconds: int = _yaml.get("bot", {}).get("cooldown_seconds", 600)

    scheduler_trigger_days: list[str] = _yaml.get("scheduler", {}).get(
        "trigger_days", ["wed", "sat"]
    )
    scheduler_trigger_hour: int = _yaml.get("scheduler", {}).get("trigger_hour", 14)
    scheduler_timezone: str = _yaml.get("scheduler", {}).get(
        "timezone", "Asia/Taipei"
    )
    scheduler_misfire_grace_time: int = _yaml.get("scheduler", {}).get(
        "misfire_grace_time", 3600
    )
    scheduler_lookback_days: int = _yaml.get("scheduler", {}).get(
        "lookback_days", 4
    )

    # Derived paths
    @property
    def data_dir(self) -> Path:
        return _ROOT / "data"

    @property
    def audio_dir(self) -> Path:
        return self.data_dir / "audio"

    @property
    def transcripts_dir(self) -> Path:
        return self.data_dir / "transcripts"

    @property
    def analyses_dir(self) -> Path:
        return self.data_dir / "analyses"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "gooaye.db"

    @property
    def logs_dir(self) -> Path:
        return _ROOT / "logs"

    @field_validator("telegram_allowed_users", mode="before")
    @classmethod
    def parse_allowed_users(cls, v: Any) -> list[int]:
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        if isinstance(v, list):
            return [int(x) for x in v]
        return []


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
