from __future__ import annotations

import pytest

from gooaye.validator import (
    InvalidYouTubeURLError,
    extract_video_id,
    to_canonical_url,
    validate_video_id,
)

VALID_ID = "dQw4w9WgXcQ"
CANONICAL = f"https://www.youtube.com/watch?v={VALID_ID}"


# ── extract_video_id ──────────────────────────────────────────────────────────

class TestExtractVideoId:
    def test_watch_url(self):
        assert extract_video_id(f"https://www.youtube.com/watch?v={VALID_ID}") == VALID_ID

    def test_watch_url_with_extra_params(self):
        url = f"https://www.youtube.com/watch?v={VALID_ID}&t=30s&list=PLxxx"
        assert extract_video_id(url) == VALID_ID

    def test_watch_url_without_www(self):
        assert extract_video_id(f"https://youtube.com/watch?v={VALID_ID}") == VALID_ID

    def test_http_scheme(self):
        assert extract_video_id(f"http://www.youtube.com/watch?v={VALID_ID}") == VALID_ID

    def test_short_url(self):
        assert extract_video_id(f"https://youtu.be/{VALID_ID}") == VALID_ID

    def test_shorts_url(self):
        assert extract_video_id(f"https://www.youtube.com/shorts/{VALID_ID}") == VALID_ID

    def test_strips_whitespace(self):
        assert extract_video_id(f"  https://youtu.be/{VALID_ID}  ") == VALID_ID

    def test_rejects_non_youtube_domain(self):
        with pytest.raises(InvalidYouTubeURLError):
            extract_video_id("https://evil.com/watch?v=dQw4w9WgXcQ")

    def test_rejects_youtube_like_domain(self):
        with pytest.raises(InvalidYouTubeURLError):
            extract_video_id("https://myoutube.com/watch?v=dQw4w9WgXcQ")

    def test_rejects_no_video_id(self):
        with pytest.raises(InvalidYouTubeURLError):
            extract_video_id("https://www.youtube.com/channel/UC123")

    def test_rejects_empty_string(self):
        with pytest.raises(InvalidYouTubeURLError):
            extract_video_id("")

    def test_rejects_plain_text(self):
        with pytest.raises(InvalidYouTubeURLError):
            extract_video_id("not a url at all")

    def test_rejects_short_video_id(self):
        # 10 chars instead of 11
        with pytest.raises(InvalidYouTubeURLError):
            extract_video_id("https://youtu.be/dQw4w9WgXc")

    def test_rejects_youtube_home(self):
        with pytest.raises(InvalidYouTubeURLError):
            extract_video_id("https://www.youtube.com/")


# ── to_canonical_url ──────────────────────────────────────────────────────────

class TestToCanonicalUrl:
    def test_watch_url_returns_canonical(self):
        url = f"https://www.youtube.com/watch?v={VALID_ID}&t=99"
        assert to_canonical_url(url) == CANONICAL

    def test_short_url_becomes_canonical(self):
        assert to_canonical_url(f"https://youtu.be/{VALID_ID}") == CANONICAL

    def test_shorts_url_becomes_canonical(self):
        assert to_canonical_url(f"https://www.youtube.com/shorts/{VALID_ID}") == CANONICAL

    def test_invalid_url_raises(self):
        with pytest.raises(InvalidYouTubeURLError):
            to_canonical_url("https://vimeo.com/123456")

    def test_canonical_form_is_stable(self):
        assert to_canonical_url(CANONICAL) == CANONICAL


# ── validate_video_id ─────────────────────────────────────────────────────────

class TestValidateVideoId:
    def test_valid_id(self):
        assert validate_video_id(VALID_ID) == VALID_ID

    def test_valid_id_with_underscores_dashes(self):
        assert validate_video_id("aB3_cD-eF4g") == "aB3_cD-eF4g"

    def test_rejects_too_short(self):
        with pytest.raises(InvalidYouTubeURLError):
            validate_video_id("short")

    def test_rejects_too_long(self):
        with pytest.raises(InvalidYouTubeURLError):
            validate_video_id("A" * 12)

    def test_rejects_special_characters(self):
        with pytest.raises(InvalidYouTubeURLError):
            validate_video_id("dQw4w9WgX!!")

    def test_rejects_empty(self):
        with pytest.raises(InvalidYouTubeURLError):
            validate_video_id("")
