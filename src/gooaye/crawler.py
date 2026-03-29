from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

import httpx
import yt_dlp

from gooaye.models import Episode
from gooaye.validator import extract_video_id

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}

_RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


def fetch_latest_videos(channel_id: str, *, client: httpx.Client | None = None) -> list[Episode]:
    """Fetch the latest videos from a YouTube channel RSS feed."""
    url = _RSS_URL.format(channel_id=channel_id)
    if client is None:
        with httpx.Client(timeout=30) as c:
            resp = c.get(url)
    else:
        resp = client.get(url)
    resp.raise_for_status()
    return _parse_rss(resp.text)


def _parse_rss(xml_text: str) -> list[Episode]:
    root = ElementTree.fromstring(xml_text)
    episodes: list[Episode] = []
    for entry in root.findall("atom:entry", _NS):
        video_id_el = entry.find("yt:videoId", _NS)
        title_el = entry.find("atom:title", _NS)
        published_el = entry.find("atom:published", _NS)
        link_el = entry.find("atom:link", _NS)

        if video_id_el is None or title_el is None or published_el is None:
            continue

        video_id = video_id_el.text or ""
        title = title_el.text or ""
        published_raw = published_el.text or ""
        url = link_el.get("href", f"https://www.youtube.com/watch?v={video_id}") if link_el is not None else f"https://www.youtube.com/watch?v={video_id}"

        try:
            publish_date = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
        except ValueError:
            publish_date = datetime.now(timezone.utc)

        episodes.append(
            Episode(
                video_id=video_id,
                title=title,
                publish_date=publish_date,
                url=url,
            )
        )
    return episodes


def check_new_videos(
    channel_id: str,
    known_ids: set[str],
    *,
    client: httpx.Client | None = None,
    published_after: datetime | None = None,
) -> list[Episode]:
    """Return episodes from the RSS feed that are not in known_ids.

    If published_after is given, only episodes published after that datetime
    are considered, preventing old backlog from being processed.
    """
    all_eps = fetch_latest_videos(channel_id, client=client)
    result = []
    for ep in all_eps:
        if ep.video_id in known_ids:
            continue
        if published_after is not None:
            pub = ep.publish_date
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            if pub <= published_after:
                continue
        result.append(ep)
    return result


def download_audio(
    video_id: str,
    output_dir: Path,
    *,
    retries: int = 3,
) -> Path:
    """Download audio for a video_id to output_dir/{video_id}.mp3.

    Returns the path to the downloaded file.
    Raises RuntimeError after all retries are exhausted.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(output_dir / f"{video_id}.%(ext)s")
    url = f"https://www.youtube.com/watch?v={video_id}"

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        "quiet": True,
        "no_warnings": True,
    }

    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            path = output_dir / f"{video_id}.mp3"
            if path.exists():
                return path
            raise RuntimeError(f"Download succeeded but file not found: {path}")
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(2 ** attempt)

    raise RuntimeError(f"Failed to download {video_id} after {retries} attempts") from last_exc


def download_audio_by_url(url: str, output_dir: Path, *, retries: int = 3) -> Path:
    """Validate URL, extract video_id, then download audio."""
    video_id = extract_video_id(url)
    return download_audio(video_id, output_dir, retries=retries)
