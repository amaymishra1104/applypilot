import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from db import db

logger = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None


def is_scheduler_enabled() -> bool:
    """Check if in-process scheduler should run (default True, set false in tests)."""
    return os.environ.get("SCHEDULER_ENABLED", "true").lower() in ("true", "1", "yes")


async def acquire_job_lease(job_id: str, lease_seconds: int = 300) -> bool:
    """Atomically acquires a distributed lease lock for the given job.
    Returns True if lease acquired; False if another worker holds an active lease."""
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    expires_iso = (now + timedelta(seconds=lease_seconds)).isoformat()
    worker_id = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"

    try:
        await db.scheduler_leases.insert_one({
            "_id": job_id,
            "job_id": job_id,
            "locked_until": None,
            "locked_by": None,
            "acquired_at": None,
        })
    except DuplicateKeyError:
        pass

    doc = await db.scheduler_leases.find_one_and_update(
        {
            "_id": job_id,
            "$or": [
                {"locked_until": None},
                {"locked_until": {"$lt": now_iso}},
            ],
        },
        {
            "$set": {
                "locked_until": expires_iso,
                "locked_by": worker_id,
                "acquired_at": now_iso,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    return doc is not None


async def release_job_lease(job_id: str) -> None:
    """Releases the lease lock on completion so next cycle can run cleanly."""
    try:
        await db.scheduler_leases.update_one(
            {"_id": job_id},
            {"$set": {"locked_until": None, "locked_by": None}},
        )
    except Exception as exc:
        logger.warning("Failed to release scheduler lease for %s: %s", job_id, exc)


async def run_with_lease(job_id: str, coro_fn: Callable, lease_seconds: int = 300) -> bool:
    """Executes a coroutine under an atomic distributed Mongo lease lock."""
    acquired = await acquire_job_lease(job_id, lease_seconds)
    if not acquired:
        logger.debug("Scheduler lease for %s already held by another worker. Skipping.", job_id)
        return False
    logger.info("Executing scheduled job '%s' under lease lock", job_id)
    try:
        await coro_fn()
        return True
    except Exception as e:
        logger.error("Scheduled job '%s' failed: %s", job_id, e, exc_info=True)
        return False
    finally:
        await release_job_lease(job_id)


async def job_autopilot():
    from application_engine import run_autopilot_cycle
    await run_with_lease("autopilot_cycle", run_autopilot_cycle, lease_seconds=600)


async def job_reply_scan():
    from application_engine import run_reply_scan_cycle
    await run_with_lease("reply_scan_cycle", run_reply_scan_cycle, lease_seconds=600)


async def job_followups():
    from application_engine import run_followup_cycle
    await run_with_lease("followup_cycle", run_followup_cycle, lease_seconds=1800)


async def job_interview_reminders():
    from application_engine import run_interview_reminder_cycle
    await run_with_lease("interview_reminder_cycle", run_interview_reminder_cycle, lease_seconds=600)


async def job_board_search():
    from routes_boards import run_board_search_cycle
    await run_with_lease("board_search_cycle", run_board_search_cycle, lease_seconds=1800)


async def job_board_digest():
    from application_engine import run_board_digest_cycle
    await run_with_lease("board_digest_cycle", run_board_digest_cycle, lease_seconds=600)


def create_scheduler() -> AsyncIOScheduler:
    """Creates and configures the AsyncIOScheduler with standard interval jobs."""
    scheduler = AsyncIOScheduler()

    # autopilot cycle: every 15 min
    scheduler.add_job(
        job_autopilot,
        trigger="interval",
        minutes=15,
        id="autopilot_cycle",
        name="Autopilot Cycle",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    # reply scan: every 30 min
    scheduler.add_job(
        job_reply_scan,
        trigger="interval",
        minutes=30,
        id="reply_scan_cycle",
        name="Reply Scan Cycle",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    # follow-ups: daily (every 24 hr)
    scheduler.add_job(
        job_followups,
        trigger="interval",
        hours=24,
        id="followup_cycle",
        name="Follow-up Cycle",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=600,
    )

    # interview reminders: every 30 min
    scheduler.add_job(
        job_interview_reminders,
        trigger="interval",
        minutes=30,
        id="interview_reminder_cycle",
        name="Interview Reminder Cycle",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    # board search: every 6 hr
    scheduler.add_job(
        job_board_search,
        trigger="interval",
        hours=6,
        id="board_search_cycle",
        name="Board Search Cycle",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=600,
    )

    # board digest: hourly check (sends at user's configured hour)
    scheduler.add_job(
        job_board_digest,
        trigger="interval",
        hours=1,
        id="board_digest_cycle",
        name="Board Digest Hourly Check",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    return scheduler


def start_scheduler() -> Optional[AsyncIOScheduler]:
    """Start the global AsyncIOScheduler if SCHEDULER_ENABLED is true."""
    global _scheduler
    if not is_scheduler_enabled():
        logger.info("Scheduler disabled via SCHEDULER_ENABLED=false")
        return None

    if _scheduler is None:
        _scheduler = create_scheduler()

    if not _scheduler.running:
        _scheduler.start()
        logger.info("APScheduler started with %d registered jobs", len(_scheduler.get_jobs()))

    return _scheduler


def stop_scheduler() -> None:
    """Stop the running scheduler cleanly."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")
    _scheduler = None


def get_scheduler() -> Optional[AsyncIOScheduler]:
    """Get the active scheduler instance."""
    return _scheduler
