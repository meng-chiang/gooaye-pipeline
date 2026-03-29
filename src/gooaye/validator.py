from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

# Accepted YouTube URL patterns
_WATCH_RE = re.compile(
    r"^https?://(?:www\.)?youtube\.com/watch\?.*v=([A-Za-z0-9_-]{11})"
)
_SHORT_RE = re.compile(r"^https?://youtu\.be/([A-Za-z0-9_-]{11})")
_SHORTS_RE = re.compile(
    r"^https?://(?:www\.)?youtube\.com/shorts/([A-Za-z0-9_-]{11})"
)

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


class InvalidYouTubeURLError(ValueError):
    pass


def extract_video_id(url: str) -> str:
    """Extract video_id from a YouTube URL.

    Raises InvalidYouTubeURLError if the URL is not a recognised YouTube URL.
    """
    url = url.strip()

    for pattern in (_WATCH_RE, _SHORT_RE, _SHORTS_RE):
        m = pattern.match(url)
        if m:
            return m.group(1)

    raise InvalidYouTubeURLError(f"Not a valid YouTube URL: {url!r}")


def to_canonical_url(url: str) -> str:
    """Return the canonical https://www.youtube.com/watch?v=<id> form."""
    video_id = extract_video_id(url)
    return f"https://www.youtube.com/watch?v={video_id}"


def validate_video_id(video_id: str) -> str:
    """Validate that a video_id consists of exactly 11 allowed characters."""
    if not _VIDEO_ID_RE.match(video_id):
        raise InvalidYouTubeURLError(f"Invalid video_id: {video_id!r}")
    return video_id
