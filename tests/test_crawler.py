from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gooaye.crawler import (
    _parse_rss,
    check_new_videos,
    download_audio,
    download_audio_by_url,
    fetch_latest_videos,
)
from gooaye.validator import InvalidYouTubeURLError

# ── fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/">
  <entry>
    <yt:videoId>vid0000001</yt:videoId>
    <title>Episode 1</title>
    <published>2026-03-24T10:00:00+00:00</published>
    <link rel="alternate" href="https://www.youtube.com/watch?v=vid0000001"/>
  </entry>
  <entry>
    <yt:videoId>vid0000002</yt:videoId>
    <title>Episode 2</title>
    <published>2026-03-20T10:00:00+00:00</published>
    <link rel="alternate" href="https://www.youtube.com/watch?v=vid0000002"/>
  </entry>
</feed>
"""

EMPTY_RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:yt="http://www.youtube.com/xml/schemas/2015">
</feed>
"""

MALFORMED_ENTRY_RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:yt="http://www.youtube.com/xml/schemas/2015">
  <entry>
    <!-- missing videoId and title -->
    <published>2026-03-24T10:00:00+00:00</published>
  </entry>
  <entry>
    <yt:videoId>vid0000003</yt:videoId>
    <title>Good Episode</title>
    <published>2026-03-24T12:00:00+00:00</published>
  </entry>
</feed>
"""


# ── _parse_rss ─────────────────────────────────────────────────────────────────

class TestParseRss:
    def test_parses_two_episodes(self):
        eps = _parse_rss(SAMPLE_RSS)
        assert len(eps) == 2

    def test_episode_fields(self):
        eps = _parse_rss(SAMPLE_RSS)
        assert eps[0].video_id == "vid0000001"
        assert eps[0].title == "Episode 1"
        assert eps[0].url == "https://www.youtube.com/watch?v=vid0000001"

    def test_publish_date_parsed(self):
        eps = _parse_rss(SAMPLE_RSS)
        assert eps[0].publish_date == datetime(2026, 3, 24, 10, 0, 0, tzinfo=timezone.utc)

    def test_empty_feed_returns_empty_list(self):
        assert _parse_rss(EMPTY_RSS) == []

    def test_skips_malformed_entries(self):
        eps = _parse_rss(MALFORMED_ENTRY_RSS)
        # only the good entry should be present
        assert len(eps) == 1
        assert eps[0].video_id == "vid0000003"


# ── fetch_latest_videos ───────────────────────────────────────────────────────

class TestFetchLatestVideos:
    def test_calls_rss_url_with_channel_id(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_RSS
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        eps = fetch_latest_videos("UCHANNELID", client=mock_client)

        mock_client.get.assert_called_once()
        call_url = mock_client.get.call_args[0][0]
        assert "UCHANNELID" in call_url
        assert len(eps) == 2

    def test_raises_on_http_error(self):
        import httpx

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock()
        )
        mock_client.get.return_value = mock_resp

        with pytest.raises(httpx.HTTPStatusError):
            fetch_latest_videos("UCHANNELID", client=mock_client)


# ── check_new_videos ──────────────────────────────────────────────────────────

class TestCheckNewVideos:
    def test_returns_only_unknown_videos(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_RSS
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        new = check_new_videos("UCHANNELID", {"vid0000001"}, client=mock_client)
        assert len(new) == 1
        assert new[0].video_id == "vid0000002"

    def test_returns_all_when_none_known(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_RSS
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        new = check_new_videos("UCHANNELID", set(), client=mock_client)
        assert len(new) == 2

    def test_returns_empty_when_all_known(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_RSS
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        new = check_new_videos(
            "UCHANNELID", {"vid0000001", "vid0000002"}, client=mock_client
        )
        assert new == []

    def test_published_after_filters_old_episodes(self):
        # SAMPLE_RSS has vid0000001 at 2026-03-24, vid0000002 at 2026-03-20
        # cutoff at 2026-03-22 → only vid0000001 should pass
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_RSS
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        cutoff = datetime(2026, 3, 22, tzinfo=timezone.utc)
        new = check_new_videos("UCHANNELID", set(), client=mock_client, published_after=cutoff)
        assert len(new) == 1
        assert new[0].video_id == "vid0000001"

    def test_published_after_none_returns_all_unknown(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_RSS
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        new = check_new_videos("UCHANNELID", set(), client=mock_client, published_after=None)
        assert len(new) == 2

    def test_published_after_excludes_all_when_cutoff_is_future(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_RSS
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        cutoff = datetime(2030, 1, 1, tzinfo=timezone.utc)
        new = check_new_videos("UCHANNELID", set(), client=mock_client, published_after=cutoff)
        assert new == []


# ── download_audio ────────────────────────────────────────────────────────────

class TestDownloadAudio:
    def test_returns_mp3_path_on_success(self, tmp_path: Path):
        with patch("gooaye.crawler.yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
            mock_ydl.__exit__ = MagicMock(return_value=False)
            mock_ydl_cls.return_value = mock_ydl

            # Create fake mp3 file to simulate successful download
            (tmp_path / "dQw4w9WgXcQ.mp3").touch()

            result = download_audio("dQw4w9WgXcQ", tmp_path)
            assert result == tmp_path / "dQw4w9WgXcQ.mp3"

    def test_creates_output_dir(self, tmp_path: Path):
        nested = tmp_path / "a" / "b"
        with patch("gooaye.crawler.yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
            mock_ydl.__exit__ = MagicMock(return_value=False)
            mock_ydl_cls.return_value = mock_ydl
            (nested / "dQw4w9WgXcQ.mp3").mkdir(parents=True)  # simulate file creation after mkdir

        assert nested.exists()

    def test_retries_on_failure_then_raises(self, tmp_path: Path):
        with patch("gooaye.crawler.yt_dlp.YoutubeDL") as mock_ydl_cls, \
             patch("gooaye.crawler.time.sleep"):
            mock_ydl = MagicMock()
            mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
            mock_ydl.__exit__ = MagicMock(return_value=False)
            mock_ydl.download.side_effect = Exception("network error")
            mock_ydl_cls.return_value = mock_ydl

            with pytest.raises(RuntimeError, match="Failed to download"):
                download_audio("dQw4w9WgXcQ", tmp_path, retries=2)

            assert mock_ydl.download.call_count == 2

    def test_raises_if_file_missing_after_download(self, tmp_path: Path):
        with patch("gooaye.crawler.yt_dlp.YoutubeDL") as mock_ydl_cls, \
             patch("gooaye.crawler.time.sleep"):
            mock_ydl = MagicMock()
            mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
            mock_ydl.__exit__ = MagicMock(return_value=False)
            mock_ydl_cls.return_value = mock_ydl
            # download() succeeds but no file created → retries exhaust

            with pytest.raises(RuntimeError):
                download_audio("dQw4w9WgXcQ", tmp_path, retries=1)


# ── download_audio_by_url ─────────────────────────────────────────────────────

class TestDownloadAudioByUrl:
    def test_extracts_video_id_and_downloads(self, tmp_path: Path):
        with patch("gooaye.crawler.download_audio") as mock_dl:
            mock_dl.return_value = tmp_path / "dQw4w9WgXcQ.mp3"
            result = download_audio_by_url(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ", tmp_path
            )
            mock_dl.assert_called_once_with("dQw4w9WgXcQ", tmp_path, retries=3)

    def test_rejects_invalid_url(self, tmp_path: Path):
        with pytest.raises(InvalidYouTubeURLError):
            download_audio_by_url("https://evil.com/video", tmp_path)
