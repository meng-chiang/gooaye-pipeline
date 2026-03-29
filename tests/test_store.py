from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from gooaye.models import Episode, EpisodeStatus
from gooaye.store import Store


def _ep(video_id: str = "vid001", title: str = "Test", days_ago: int = 0) -> Episode:
    return Episode(
        video_id=video_id,
        title=title,
        publish_date=datetime(2026, 3, 24, tzinfo=timezone.utc) - timedelta(days=days_ago),
        url=f"https://www.youtube.com/watch?v={video_id}",
    )


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "test.db")


# ── init ──────────────────────────────────────────────────────────────────────

class TestInit:
    def test_db_file_created(self, tmp_path: Path):
        db = tmp_path / "sub" / "test.db"
        Store(db)
        assert db.exists()

    def test_tables_exist(self, store: Store):
        with store._conn() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "episodes" in tables
        assert "rate_limits" in tables

    def test_wal_mode(self, store: Store):
        with store._conn() as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"


# ── episodes CRUD ─────────────────────────────────────────────────────────────

class TestEpisodeCRUD:
    def test_add_and_get(self, store: Store):
        ep = _ep()
        store.add_episode(ep)
        result = store.get_episode("vid001")
        assert result is not None
        assert result.video_id == "vid001"
        assert result.title == "Test"

    def test_get_nonexistent_returns_none(self, store: Store):
        assert store.get_episode("missing") is None

    def test_add_is_idempotent(self, store: Store):
        ep = _ep()
        store.add_episode(ep)
        store.add_episode(ep)  # should not raise
        with store._conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM episodes WHERE video_id='vid001'"
            ).fetchone()[0]
        assert count == 1

    def test_update_status(self, store: Store):
        store.add_episode(_ep())
        store.update_status("vid001", EpisodeStatus.DONE, analysis_result="摘要內容")
        ep = store.get_episode("vid001")
        assert ep.status == EpisodeStatus.DONE
        assert ep.analysis_result == "摘要內容"

    def test_update_status_with_error(self, store: Store):
        store.add_episode(_ep())
        store.update_status("vid001", EpisodeStatus.FAILED, error_message="download failed")
        ep = store.get_episode("vid001")
        assert ep.status == EpisodeStatus.FAILED
        assert ep.error_message == "download failed"

    def test_is_processed_false_for_pending(self, store: Store):
        store.add_episode(_ep())
        assert not store.is_processed("vid001")

    def test_is_processed_true_for_done(self, store: Store):
        store.add_episode(_ep())
        store.update_status("vid001", EpisodeStatus.DONE)
        assert store.is_processed("vid001")

    def test_is_processed_false_for_missing(self, store: Store):
        assert not store.is_processed("missing")


# ── cache ─────────────────────────────────────────────────────────────────────

class TestCacheAnalysis:
    def test_returns_none_when_no_episode(self, store: Store):
        assert store.get_cached_analysis("vid001") is None

    def test_returns_none_when_not_done(self, store: Store):
        store.add_episode(_ep())
        store.update_status("vid001", EpisodeStatus.ANALYZING, analysis_result="partial")
        assert store.get_cached_analysis("vid001") is None

    def test_returns_result_when_done(self, store: Store):
        store.add_episode(_ep())
        store.update_status("vid001", EpisodeStatus.DONE, analysis_result="完整摘要")
        assert store.get_cached_analysis("vid001") == "完整摘要"

    def test_returns_none_when_done_but_empty_result(self, store: Store):
        store.add_episode(_ep())
        store.update_status("vid001", EpisodeStatus.DONE, analysis_result="")
        assert store.get_cached_analysis("vid001") is None


# ── list & delete ─────────────────────────────────────────────────────────────

class TestListAndDelete:
    def test_list_episodes_empty(self, store: Store):
        assert store.list_episodes() == []

    def test_list_episodes_ordered_by_date_desc(self, store: Store):
        store.add_episode(_ep("vid1", days_ago=2))
        store.add_episode(_ep("vid2", days_ago=0))
        store.add_episode(_ep("vid3", days_ago=5))
        eps = store.list_episodes()
        assert [e.video_id for e in eps] == ["vid2", "vid1", "vid3"]

    def test_list_episodes_respects_limit(self, store: Store):
        for i in range(5):
            store.add_episode(_ep(f"vid{i}", days_ago=i))
        assert len(store.list_episodes(limit=3)) == 3

    def test_delete_old_episodes_within_keep(self, store: Store):
        for i in range(3):
            store.add_episode(_ep(f"vid{i}", days_ago=i))
        deleted = store.delete_old_episodes(keep=5)
        assert deleted == 0

    def test_delete_old_episodes_removes_oldest(self, store: Store):
        for i in range(5):
            store.add_episode(_ep(f"vid{i}", days_ago=i))
        deleted = store.delete_old_episodes(keep=3)
        assert deleted == 2
        remaining = [e.video_id for e in store.list_episodes()]
        assert "vid3" not in remaining
        assert "vid4" not in remaining


# ── rate limits ───────────────────────────────────────────────────────────────

class TestRateLimits:
    def test_get_last_request_none_for_new_user(self, store: Store):
        assert store.get_last_request_time(999) is None

    def test_set_and_get_last_request_time(self, store: Store):
        ts = datetime(2026, 3, 24, 12, 0, 0, tzinfo=timezone.utc)
        store.set_last_request_time(42, at=ts)
        result = store.get_last_request_time(42)
        assert result is not None
        assert result.replace(tzinfo=timezone.utc) == ts.replace(tzinfo=timezone.utc)

    def test_set_last_request_time_upsert(self, store: Store):
        t1 = datetime(2026, 3, 24, 10, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 3, 24, 11, 0, 0, tzinfo=timezone.utc)
        store.set_last_request_time(42, at=t1)
        store.set_last_request_time(42, at=t2)
        result = store.get_last_request_time(42)
        assert result.replace(tzinfo=timezone.utc).hour == 11

    def test_is_rate_limited_false_for_new_user(self, store: Store):
        assert not store.is_rate_limited(999, cooldown_seconds=600)

    def test_is_rate_limited_true_within_cooldown(self, store: Store):
        recent = datetime.now(timezone.utc) - timedelta(seconds=100)
        store.set_last_request_time(42, at=recent)
        assert store.is_rate_limited(42, cooldown_seconds=600)

    def test_is_rate_limited_false_after_cooldown(self, store: Store):
        old = datetime.now(timezone.utc) - timedelta(seconds=700)
        store.set_last_request_time(42, at=old)
        assert not store.is_rate_limited(42, cooldown_seconds=600)
