import asyncio
import hashlib
import hmac
import logging
import os

from fastapi import APIRouter, HTTPException, Request

from application_engine import run_autopilot_cycle, run_followup_cycle, run_interview_reminder_cycle, run_reply_scan_cycle
from db import db, utc_now_iso

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["crons"])


def verify_cron(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    expected = os.environ.get("WEBHOOK_CRON_SECRET", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else ""
    if not expected or not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return request.headers.get("x-webhook-id", "")


async def _claim_run(run_id: str) -> bool:
    if not run_id:
        return True
    fingerprint = hashlib.sha256(run_id.encode()).hexdigest()[:32]
    existing = await db.cron_runs.find_one({"run_id": fingerprint})
    if existing:
        return False
    await db.cron_runs.insert_one({"run_id": fingerprint, "created_at": utc_now_iso()})
    return True


# Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
@router.post("/cron/autopilot")
async def cron_autopilot(request: Request):
    run_id = verify_cron(request)
    if not await _claim_run(run_id):
        return {"ok": True, "duplicate": True}
    asyncio.create_task(_safe(run_autopilot_cycle(), "autopilot"))
    return {"ok": True, "accepted": "autopilot"}


# Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
@router.post("/cron/scan-replies")
async def cron_scan_replies(request: Request):
    run_id = verify_cron(request)
    if not await _claim_run(run_id):
        return {"ok": True, "duplicate": True}
    asyncio.create_task(_safe(run_reply_scan_cycle(), "scan-replies"))
    return {"ok": True, "accepted": "scan-replies"}


# Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
@router.post("/cron/followups")
async def cron_followups(request: Request):
    run_id = verify_cron(request)
    if not await _claim_run(run_id):
        return {"ok": True, "duplicate": True}
    asyncio.create_task(_safe(run_followup_cycle(), "followups"))
    return {"ok": True, "accepted": "followups"}


# Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
@router.post("/cron/interview-reminders")
async def cron_interview_reminders(request: Request):
    run_id = verify_cron(request)
    if not await _claim_run(run_id):
        return {"ok": True, "duplicate": True}
    asyncio.create_task(_safe(run_interview_reminder_cycle(), "interview-reminders"))
    return {"ok": True, "accepted": "interview-reminders"}


# Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
@router.post("/cron/board-search")
async def cron_board_search(request: Request):
    from routes_boards import run_board_search_cycle
    run_id = verify_cron(request)
    if not await _claim_run(run_id):
        return {"ok": True, "duplicate": True}
    asyncio.create_task(_safe(run_board_search_cycle(), "board-search"))
    return {"ok": True, "accepted": "board-search"}


# Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
@router.post("/cron/board-digest")
async def cron_board_digest(request: Request):
    from application_engine import run_board_digest_cycle
    run_id = verify_cron(request)
    if not await _claim_run(run_id):
        return {"ok": True, "duplicate": True}
    asyncio.create_task(_safe(run_board_digest_cycle(), "board-digest"))
    return {"ok": True, "accepted": "board-digest"}


async def _safe(coro, name):
    try:
        result = await coro
        logger.info("Cron cycle %s finished: %s", name, result)
    except Exception:
        logger.exception("Cron cycle %s failed", name)
