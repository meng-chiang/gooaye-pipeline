from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class EpisodeStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    ANALYZING = "analyzing"
    NOTIFYING = "notifying"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Episode:
    video_id: str
    title: str
    publish_date: datetime
    url: str
    status: EpisodeStatus = EpisodeStatus.PENDING
    analysis_result: str = ""
    error_message: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def canonical_url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


@dataclass
class Transcript:
    video_id: str
    text: str
    language: str = "zh"
    segments: list[dict] = field(default_factory=list)

    @property
    def word_count(self) -> int:
        return len(self.text)


@dataclass
class Analysis:
    video_id: str
    title: str
    publish_date: datetime
    summary: str
    raw_transcript_trimmed: str = ""
    model_used: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def format_for_telegram(self) -> str:
        date_str = self.publish_date.strftime("%Y-%m-%d")
        return f"📊 *{self.title}*\n📅 {date_str}\n\n{self.summary}"
