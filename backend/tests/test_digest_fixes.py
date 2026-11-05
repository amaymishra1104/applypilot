# Retest of iteration_5 digest fixes: empty timezone 400, send-now 0 jobs, cycle iterates users w/o settings doc
import asyncio
import sys

import pytest
from dotenv import dotenv_values, load_dotenv
from pymongo import MongoClient

ENV = dotenv_values("backend/.env") or dotenv_values("/app/backend/.env") or {}
MONGO_URL = ENV.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = ENV.get("DB_NAME", "applypilot_test")
MDB = MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module", autouse=True)
def restore(api):
    yield
    api.put("/api/settings", json={"digest": {"enabled": True, "hour": 8, "timezone": "UTC"}})


def test_empty_timezone_400(api):
    r = api.put("/api/settings", json={"digest": {"timezone": ""}})
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "Unknown timezone"
    assert api.get("/api/settings").json()["digest"]["timezone"] == "UTC"


def test_hour_out_of_range_422_detail_list(api):
    r = api.put("/api/settings", json={"digest": {"hour": 30}})
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], list)


def test_send_now_zero_jobs(api):
    r = api.post("/api/settings/digest/send-now")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True and d["jobs"] == 0 and d["sent_to"] is None


def test_cycle_includes_user_without_settings_doc():
    u = MDB.users.find_one({"email": "pilot-second@applypilot.dev"}, {"user_id": 1})
    uid = u["user_id"]
    had_doc = MDB.app_settings.find_one({"user_id": uid}) is not None
    sys.path.insert(0, "/app/backend")
    load_dotenv("/app/backend/.env")
    import application_engine as ae
    try:
        async def both():
            return (await ae.run_board_digest_cycle(user_id=uid, force=True),
                    await ae.run_board_digest_cycle(user_id=uid))
        summary, summary2 = asyncio.run(both())
        assert summary["users"] == 1, summary
        assert summary["emails"] == 0 and summary.get("last_count") == 0
        doc = MDB.app_settings.find_one({"user_id": uid}, {"_id": 0, "digest": 1})
        assert doc and doc["digest"].get("last_sent_date")
        # non-forced: default hour 8 / already sent today -> skipped
        assert summary2["users"] == 0
    finally:
        if not had_doc:
            MDB.app_settings.delete_one({"user_id": uid})
