import os
import sys

# Ensure DB_NAME points to applypilot_test for testing
os.environ["DB_NAME"] = "applypilot_test"
os.environ["DRY_RUN"] = "false"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ.setdefault("OWNER_EMAIL", "owner@applypilot.dev")
os.environ.setdefault("OWNER_PASSWORD_HASH", "$2b$12$aCdSlPdvtDVi9woG9kKGIewm0o1.l6wR7u2V4w5QOQ/PHdbyIyogy")
os.environ.setdefault("SESSION_SECRET", "test_session_secret_for_applypilot_owner_12345")
os.environ.setdefault("APP_ENCRYPTION_KEY", "4SloZgHIl31EvC5tYwA-IdT6ZXc6R5JulFBEdZrgRrE=")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from dotenv import dotenv_values

FRONT_ENV = dotenv_values("frontend/.env") or {}
BASE_URL = (FRONT_ENV.get("REACT_APP_BACKEND_URL") or "http://localhost:8000").rstrip("/")


@pytest.fixture(scope="session", autouse=True)
def test_db_lifecycle(request):
    yield
    # If running under xdist, workers must not drop the database while peer workers are still running.
    # The master process drops it in pytest_sessionfinish after all workers exit.
    if not hasattr(request.config, "workerinput"):
        _drop_test_db()


def pytest_sessionfinish(session, exitstatus):
    # Runs on the master controller after all xdist workers finish, or in serial mode
    if not hasattr(session.config, "workerinput"):
        _drop_test_db()


def _drop_test_db():
    from pymongo import MongoClient
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    try:
        client = MongoClient(mongo_url)
        client.drop_database("applypilot_test")
        client.close()
    except Exception:
        pass
