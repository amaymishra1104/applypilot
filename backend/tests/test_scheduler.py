import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from db import db
from scheduler import (
    acquire_job_lease,
    create_scheduler,
    is_scheduler_enabled,
    release_job_lease,
    run_with_lease,
    start_scheduler,
    stop_scheduler,
)
from server import app


def test_scheduler_job_specifications():
    scheduler = create_scheduler()
    jobs = {j.id: j for j in scheduler.get_jobs()}

    expected_jobs = [
        "autopilot_cycle",
        "reply_scan_cycle",
        "followup_cycle",
        "interview_reminder_cycle",
        "board_search_cycle",
        "board_digest_cycle",
    ]

    for job_id in expected_jobs:
        assert job_id in jobs, f"Missing expected scheduled job {job_id}"
        job = jobs[job_id]
        assert job.coalesce is True
        assert job.max_instances == 1


@pytest.mark.asyncio
async def test_scheduler_toggle_via_env(monkeypatch):
    stop_scheduler()

    # When disabled
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    assert is_scheduler_enabled() is False
    assert start_scheduler() is None

    # When enabled
    monkeypatch.setenv("SCHEDULER_ENABLED", "true")
    assert is_scheduler_enabled() is True
    s = start_scheduler()
    assert s is not None
    assert s.running is True

    # Clean shutdown
    stop_scheduler()
    await asyncio.sleep(0.05)
    assert s.running is False


@pytest.mark.asyncio
async def test_distributed_lease_lock_mutual_exclusion():
    job_id = "test_autopilot_lease"
    await db.scheduler_leases.delete_many({"_id": job_id})

    # Worker 1 acquires lease
    acquired_1 = await acquire_job_lease(job_id, lease_seconds=120)
    assert acquired_1 is True

    # Worker 2 attempts while active -> must be rejected
    acquired_2 = await acquire_job_lease(job_id, lease_seconds=120)
    assert acquired_2 is False

    # Worker 1 completes and releases lease
    await release_job_lease(job_id)

    # Worker 2 attempts again -> should now succeed
    acquired_3 = await acquire_job_lease(job_id, lease_seconds=120)
    assert acquired_3 is True

    await release_job_lease(job_id)


@pytest.mark.asyncio
async def test_distributed_lease_lock_expired_recovery():
    job_id = "test_expired_lease"
    # Seed an expired lease in the past
    past_iso = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    await db.scheduler_leases.update_one(
        {"_id": job_id},
        {"$set": {"locked_until": past_iso, "locked_by": "stale_dead_worker"}},
        upsert=True,
    )

    # New worker should claim expired lease without error
    claimed = await acquire_job_lease(job_id, lease_seconds=60)
    assert claimed is True

    doc = await db.scheduler_leases.find_one({"_id": job_id})
    assert doc is not None
    assert doc["locked_until"] > datetime.now(timezone.utc).isoformat()
    await release_job_lease(job_id)


@pytest.mark.asyncio
async def test_run_with_lease_skips_when_locked():
    job_id = "test_skip_when_locked"
    await db.scheduler_leases.delete_many({"_id": job_id})

    called = 0

    async def sample_task():
        nonlocal called
        called += 1
        await asyncio.sleep(0.01)

    # First run succeeds
    success = await run_with_lease(job_id, sample_task)
    assert success is True
    assert called == 1

    # Simulate active lease held by another worker
    await acquire_job_lease(job_id, lease_seconds=60)

    # Second run is skipped
    second_run = await run_with_lease(job_id, sample_task)
    assert second_run is False
    assert called == 1  # Unchanged

    await release_job_lease(job_id)


def test_fastapi_lifespan_starts_and_stops_scheduler(monkeypatch):
    monkeypatch.setenv("SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("OWNER_EMAIL", "owner@applypilot.dev")
    monkeypatch.setenv("SESSION_SECRET", "session_secret_for_lifespan_test_32ch")
    monkeypatch.setenv("OWNER_PASSWORD_HASH", "$2b$12$e8q4K2aI58m4eI9BqV3Q7.wV1u3mR6e5zB3kY2lO0bK7iO6fN6O9u")

    from scheduler import get_scheduler

    with TestClient(app) as client:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        # Scheduler should be running during lifespan
        sched = get_scheduler()
        assert sched is not None
        assert sched.running is True

    # After exiting lifespan context, scheduler should be stopped
    sched = get_scheduler()
    assert sched is None
