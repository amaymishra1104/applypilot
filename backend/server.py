import asyncio
import logging
import os
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from pymongo import ASCENDING, DESCENDING, IndexModel

from db import db, client
from clerk_auth import clerk_router
from routes_roles import router as roles_router
from routes_contacts import router as contacts_router
from routes_opportunities import router as opportunities_router
from routes_applications import router as applications_router
from routes_tracking import router as tracking_router
from routes_gmail import router as gmail_router
from routes_settings import router as settings_router
from routes_dashboard import router as dashboard_router
from cron_routes import router as cron_router
from routes_boards import router as boards_router

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

INDEXES: dict[str, list[IndexModel]] = {
    "users": [IndexModel([("user_id", ASCENDING)], name="user_id", unique=True)],
    "role_profiles": [IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="user_created")],
    "resume_versions": [
        IndexModel([("user_id", ASCENDING), ("role_profile_id", ASCENDING)], name="user_role"),
        IndexModel([("user_id", ASCENDING), ("active", ASCENDING)], name="user_active"),
    ],
    "hr_contacts": [
        IndexModel([("user_id", ASCENDING), ("hr_email_norm", ASCENDING)], name="user_email"),
        IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="user_created"),
    ],
    "companies": [IndexModel([("user_id", ASCENDING), ("name", ASCENDING)], name="user_name")],
    "job_opportunities": [
        IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="user_created"),
        IndexModel([("user_id", ASCENDING), ("job_title_norm", ASCENDING)], name="user_title"),
    ],
    "job_matches": [IndexModel([("user_id", ASCENDING), ("opportunity_id", ASCENDING)], name="user_opp")],
    "job_applications": [
        IndexModel([("user_id", ASCENDING), ("status", ASCENDING)], name="user_status"),
        IndexModel([("user_id", ASCENDING), ("sent_at", DESCENDING)], name="user_sent"),
        IndexModel([("user_id", ASCENDING), ("hr_email", ASCENDING), ("job_title_norm", ASCENDING)],
                   name="user_dupe_check"),
    ],
    "application_events": [
        IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="user_created"),
        IndexModel([("user_id", ASCENDING), ("application_id", ASCENDING)], name="user_app"),
    ],
    "follow_ups": [
        IndexModel([("user_id", ASCENDING), ("status", ASCENDING)], name="user_status"),
        IndexModel([("user_id", ASCENDING), ("application_id", ASCENDING)], name="user_app"),
    ],
    "gmail_connections": [IndexModel([("user_id", ASCENDING)], name="user_id", unique=True)],
    "oauth_states": [
        IndexModel([("state", ASCENDING)], name="state", unique=True),
        IndexModel([("expires_at", ASCENDING)], name="expires_at", expireAfterSeconds=0),
    ],
    "app_settings": [IndexModel([("user_id", ASCENDING)], name="user_id", unique=True)],
    "google_oauth_config": [IndexModel([("user_id", ASCENDING)], name="user_id", unique=True)],
    "reply_scan_state": [IndexModel([("user_id", ASCENDING)], name="user_id", unique=True)],
    "extension_tokens": [IndexModel([("token_hash", ASCENDING)], name="token_hash", unique=True),
                         IndexModel([("user_id", ASCENDING)], name="user_id")],
    "board_search_runs": [IndexModel([("user_id", ASCENDING), ("started_at", DESCENDING)], name="user_started")],
    "cron_runs": [IndexModel([("created_at", ASCENDING)], name="created_at", expireAfterSeconds=172800)],
}


async def ensure_indexes() -> None:
    for collection, models in INDEXES.items():
        for model in models:  # one at a time so a bad spec skips only itself
            try:
                await db[collection].create_indexes([model])
            except Exception as exc:
                logger.error("ensure_indexes(%s.%s): %s", collection, model.document["name"], exc)


app = FastAPI(title="ApplyPilot API")

api_router = APIRouter(prefix="/api")


@api_router.get("/")
async def root():
    return {"message": "ApplyPilot API is running"}


@api_router.get("/health")
async def health():
    return {"status": "healthy"}


app.include_router(clerk_router)
for router in (roles_router, contacts_router, opportunities_router, applications_router,
               tracking_router, gmail_router, settings_router, dashboard_router, cron_router, boards_router):
    app.include_router(router)
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    app.state.index_task = asyncio.create_task(ensure_indexes())
    asyncio.create_task(_init_storage())
    asyncio.create_task(_cleanup_oauth_states())
    asyncio.create_task(resume_running_bulk_jobs())


async def resume_running_bulk_jobs() -> list[str]:
    """On app start, find bulk_jobs in 'running' and continue them without duplicating applications."""
    resumed = []
    try:
        from routes_contacts import run_bulk_generation_job
        running_jobs = await db.bulk_jobs.find({"status": "running"}).to_list(100)
        for job in running_jobs:
            logger.info("Resuming interrupted bulk job %s for user %s", job["id"], job["user_id"])
            asyncio.create_task(run_bulk_generation_job(job["id"], job["user_id"]))
            resumed.append(job["id"])
    except Exception as exc:
        logger.error("Failed to resume running bulk jobs: %s", exc)
    return resumed


async def _init_storage():
    try:
        from storage import init_storage
        await asyncio.to_thread(init_storage)
        logger.info("Storage initialized")
    except Exception as exc:
        logger.error("Storage init failed: %s", exc)


async def _cleanup_oauth_states():
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        await db.oauth_states.delete_many({"expires_at": {"$lt": cutoff}})
    except Exception as exc:
        logger.error("oauth_states cleanup failed: %s", exc)


@app.on_event("shutdown")
async def shutdown_db_client():
    task = getattr(app.state, "index_task", None)
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    client.close()
