from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from gooaye.models import Episode, EpisodeStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Store:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS episodes (
                    video_id        TEXT PRIMARY KEY,
                    title           TEXT NOT NULL,
                    publish_date    TEXT NOT NULL,
                    url             TEXT NOT NULL,
                    status          TEXT NOT NULL DEFAULT 'pending',
                    analysis_result TEXT NOT NULL DEFAULT '',
                    error_message   TEXT NOT NULL DEFAULT '',
                    created_at      TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS rate_limits (
                    user_id         INTEGER PRIMARY KEY,
                    last_request_at TEXT NOT NULL
                )
            """)

    # ── episodes ──────────────────────────────────────────────────────────────

    def add_episode(self, episode: Episode) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO episodes
                    (video_id, title, publish_date, url, status,
                     analysis_result, error_message, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    episode.video_id,
                    episode.title,
                    episode.publish_date.isoformat(),
                    episode.url,
                    episode.status.value,
                    episode.analysis_result,
                    episode.error_message,
                    episode.created_at.isoformat(),
                ),
            )

    def get_episode(self, video_id: str) -> Episode | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM episodes WHERE video_id = ?", (video_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_episode(row)

    def is_processed(self, video_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT status FROM episodes WHERE video_id = ?", (video_id,)
            ).fetchone()
        return row is not None and row["status"] == EpisodeStatus.DONE.value

    def update_status(
        self,
        video_id: str,
        status: EpisodeStatus,
        analysis_result: str = "",
        error_message: str = "",
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE episodes
                SET status = ?, analysis_result = ?, error_message = ?
                WHERE video_id = ?
                """,
                (status.value, analysis_result, error_message, video_id),
            )

    def get_cached_analysis(self, video_id: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT analysis_result, status FROM episodes WHERE video_id = ?",
                (video_id,),
            ).fetchone()
        if row and row["status"] == EpisodeStatus.DONE.value and row["analysis_result"]:
            return row["analysis_result"]
        return None

    def list_episodes(self, limit: int = 20) -> list[Episode]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM episodes ORDER BY publish_date DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_episode(r) for r in rows]

    def delete_old_episodes(self, keep: int = 20) -> int:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT video_id FROM episodes ORDER BY publish_date DESC"
            ).fetchall()
        if len(rows) <= keep:
            return 0
        to_delete = [r["video_id"] for r in rows[keep:]]
        with self._conn() as conn:
            conn.executemany(
                "DELETE FROM episodes WHERE video_id = ?",
                [(vid,) for vid in to_delete],
            )
        return len(to_delete)

    # ── rate limits ───────────────────────────────────────────────────────────

    def get_last_request_time(self, user_id: int) -> datetime | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT last_request_at FROM rate_limits WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(row["last_request_at"])

    def set_last_request_time(self, user_id: int, at: datetime | None = None) -> None:
        ts = (at or _now()).isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO rate_limits (user_id, last_request_at)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET last_request_at = excluded.last_request_at
                """,
                (user_id, ts),
            )

    def is_rate_limited(self, user_id: int, cooldown_seconds: int) -> bool:
        last = self.get_last_request_time(user_id)
        if last is None:
            return False
        last = last.replace(tzinfo=timezone.utc) if last.tzinfo is None else last
        elapsed = (_now() - last).total_seconds()
        return elapsed < cooldown_seconds

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_episode(row: sqlite3.Row) -> Episode:
        return Episode(
            video_id=row["video_id"],
            title=row["title"],
            publish_date=datetime.fromisoformat(row["publish_date"]),
            url=row["url"],
            status=EpisodeStatus(row["status"]),
            analysis_result=row["analysis_result"],
            error_message=row["error_message"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
