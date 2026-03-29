from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from gooaye.scheduler import _days_to_cron, build_scheduler


# ── _days_to_cron ─────────────────────────────────────────────────────────────

class TestDaysToCron:
    def test_single_day(self):
        assert _days_to_cron(["wed"]) == "wed"

    def test_multiple_days(self):
        assert _days_to_cron(["wed", "sat"]) == "wed,sat"

    def test_case_insensitive(self):
        assert _days_to_cron(["WED", "SAT"]) == "wed,sat"

    def test_all_days(self):
        days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        result = _days_to_cron(days)
        assert result == "mon,tue,wed,thu,fri,sat,sun"


# ── build_scheduler ───────────────────────────────────────────────────────────

def _make_settings(
    days: list[str] = None,
    hour: int = 14,
    tz: str = "Asia/Taipei",
    misfire: int = 3600,
) -> MagicMock:
    s = MagicMock()
    s.scheduler_trigger_days = days or ["wed", "sat"]
    s.scheduler_trigger_hour = hour
    s.scheduler_timezone = tz
    s.scheduler_misfire_grace_time = misfire
    return s


class TestBuildScheduler:
    def test_returns_asyncio_scheduler(self):
        settings = _make_settings()
        scheduler = build_scheduler(settings, AsyncMock())
        assert isinstance(scheduler, AsyncIOScheduler)

    def test_job_added_with_correct_id(self):
        settings = _make_settings()
        scheduler = build_scheduler(settings, AsyncMock())
        job = scheduler.get_job("check_new_videos")
        assert job is not None

    def test_job_uses_cron_trigger(self):
        settings = _make_settings()
        scheduler = build_scheduler(settings, AsyncMock())
        job = scheduler.get_job("check_new_videos")
        assert isinstance(job.trigger, CronTrigger)

    def test_job_trigger_includes_configured_days(self):
        settings = _make_settings(days=["wed", "sat"])
        scheduler = build_scheduler(settings, AsyncMock())
        job = scheduler.get_job("check_new_videos")
        trigger_str = str(job.trigger)
        assert "wed" in trigger_str or "3" in trigger_str
        assert job is not None

    def test_job_trigger_runs_every_two_hours_after_1pm(self):
        settings = _make_settings()
        scheduler = build_scheduler(settings, AsyncMock())
        job = scheduler.get_job("check_new_videos")
        trigger_str = str(job.trigger)
        assert "13" in trigger_str
        assert "15" in trigger_str
        assert "23" in trigger_str

    def test_misfire_grace_time_set(self):
        settings = _make_settings(misfire=7200)
        scheduler = build_scheduler(settings, AsyncMock())
        job = scheduler.get_job("check_new_videos")
        assert job.misfire_grace_time == 7200

    def test_scheduler_timezone_set(self):
        settings = _make_settings(tz="Asia/Taipei")
        scheduler = build_scheduler(settings, AsyncMock())
        assert str(scheduler.timezone) == "Asia/Taipei"

    def test_scheduler_not_started_after_build(self):
        settings = _make_settings()
        scheduler = build_scheduler(settings, AsyncMock())
        assert not scheduler.running

    def test_job_coalesce_enabled(self):
        settings = _make_settings()
        scheduler = build_scheduler(settings, AsyncMock())
        job = scheduler.get_job("check_new_videos")
        assert job.coalesce is True
