from __future__ import annotations

import logging
from typing import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from gooaye.config import Settings

logger = logging.getLogger(__name__)

def _days_to_cron(days: list[str]) -> str:
    return ",".join(d.lower() for d in days)


def build_scheduler(
    settings: Settings,
    check_and_run: Callable,
) -> AsyncIOScheduler:
    """Create and configure an AsyncIOScheduler with Wed/Sat triggers.

    check_and_run: async callable that checks RSS and runs pipeline for new episodes.
    """
    scheduler = AsyncIOScheduler(timezone=settings.scheduler_timezone)
    day_of_week = _days_to_cron(settings.scheduler_trigger_days)

    trigger = CronTrigger(
        day_of_week=day_of_week,
        hour="13,15,17,19,21,23",
        minute=0,
        timezone=settings.scheduler_timezone,
    )

    scheduler.add_job(
        check_and_run,
        trigger=trigger,
        id="check_new_videos",
        name="Check new Gooaye episodes",
        misfire_grace_time=settings.scheduler_misfire_grace_time,
        coalesce=True,
    )

    return scheduler
