"""APScheduler wrapper with lazy-fetch lock helpers."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Iterable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from . import arxiv as arxiv_mod
from . import db

log = logging.getLogger(__name__)

# Lazy-fetch locks: key = "<cat>:<YYYY-MM-DD>" -> asyncio.Lock
_locks: dict[str, asyncio.Lock] = {}
_lock_guard = asyncio.Lock()


async def get_lock(key: str) -> asyncio.Lock:
    async with _lock_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _locks[key] = lock
        return lock


def start_scheduler(categories: Iterable[str]) -> AsyncIOScheduler:
    """Schedule a daily 03:00 SGT (UTC+8 -> 19:00 UTC) fetch."""
    sched = AsyncIOScheduler(timezone="UTC")
    cats = list(categories)

    async def job():
        log.info("scheduled fetch start for %s", cats)
        try:
            counts = await arxiv_mod.fetch_categories(cats, enrich=True, delay=1.2)
            log.info("scheduled fetch done: %s", counts)
        except Exception:
            log.exception("scheduled fetch failed")

    # 03:00 SGT = 19:00 UTC (previous day). Use UTC hour=19 to match.
    sched.add_job(job, CronTrigger(hour=19, minute=0))
    sched.start()
    log.info("scheduler started (daily 19:00 UTC = 03:00 SGT) for %s", cats)
    return sched


async def lazy_fetch_if_needed(category: str) -> None:
    """If today's data for this category isn't in DB, fetch it (under a lock)."""
    today = datetime.now(timezone.utc).date().isoformat()
    if db.has_fetch(category, today):
        return
    key = f"{category}:{today}"
    lock = await get_lock(key)
    async with lock:
        # re-check after acquiring
        if db.has_fetch(category, today):
            return
        log.info("lazy fetch %s for %s", category, today)
        try:
            await arxiv_mod.fetch_categories([category], enrich=True, delay=1.0)
        except Exception:
            log.exception("lazy fetch failed for %s", category)
