# Daily Board Digest: settings.digest defaults/validation/persistence, send-now counts, cron auth,
# run_board_digest_cycle local-hour + once-per-local-day gating (last_sent_date in settings.digest).
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

from conftest import BASE_URL

ENV = dotenv_values("/app/backend/.env")
CRON = ENV.get("WEBHOOK_CRON_SECRET")
MDB = MongoClient(ENV["MONGO_URL"])[ENV["DB_NAME"]]
TAG = uuid.uuid4().hex[:8]
STATE = {"opps": [], "apps": []}
TZ = "Asia/Kolkata"


def ext(t):
    return {"X-ApplyPilot-Token": t}


def uid():
    return MDB.users.find_one({"email": "pilot-tester@applypilot.dev"}, {"user_id": 1})["user_id"]


def digest_doc():
    return (MDB.app_settings.find_one({"user_id": uid()}, {"_id": 0, "digest": 1}) or {}).get("digest") or {}


def cron(headers=None):
    return requests.post(f"{BASE_URL}/api/cron/board-digest", headers=headers or {}, timeout=30)


def cron_ok():
    r = cron({"Authorization": f"Bearer {CRON}", "X-Webhook-Id": f"test-digest-{uuid.uuid4().hex}"})
    assert r.status_code == 200, r.text
    assert r.json().get("accepted") == "board-digest"
    time.sleep(4)


@pytest.fixture(scope="module", autouse=True)
def lifecycle(api):
    STATE["orig_autopilot"] = api.get("/api/autopilot").json()["autopilot"]
    yield
    u = uid()
    for aid in STATE["apps"]:
        MDB.job_applications.delete_one({"id": aid, "user_id": u})
    for oid in STATE["opps"]:
        MDB.job_applications.delete_many({"opportunity_id": oid, "user_id": u})
        MDB.job_matches.delete_many({"opportunity_id": oid, "user_id": u})
        api.delete(f"/api/opportunities/{oid}")
    MDB.application_events.delete_many({"user_id": u, "type": "board_digest", "created_at": {"$gte": STATE.get("t0", "")}})
    api.put("/api/settings", json={"digest": {"enabled": True, "hour": 8, "timezone": "UTC"}})
    MDB.app_settings.update_one({"user_id": u}, {"$unset": {"digest.last_sent_date": "", "digest.last_sent_at": ""}})
    o = STATE["orig_autopilot"]
    api.put("/api/autopilot", json={"mode": o["mode"], "paused": False, "enabled": o["enabled"]})
    api.delete("/api/boards/extension-token")


class TestDigestSettings:
    def test_defaults(self, api):
        STATE["t0"] = datetime.utcnow().isoformat()
        d = api.get("/api/settings").json()["digest"]
        assert d["enabled"] is True and d["hour"] == 8 and d["timezone"] == "UTC", d

    def test_requires_auth(self):
        assert requests.post(f"{BASE_URL}/api/settings/digest/send-now", timeout=20).status_code == 401
        assert requests.get(f"{BASE_URL}/api/settings", timeout=20).status_code == 401

    def test_validation(self, api):
        assert api.put("/api/settings", json={"digest": {"hour": 24}}).status_code == 422
        assert api.put("/api/settings", json={"digest": {"hour": -1}}).status_code == 422
        r = api.put("/api/settings", json={"digest": {"timezone": "Mars/Base"}})
        assert r.status_code == 400 and "timezone" in r.json()["detail"].lower()
        assert api.get("/api/settings").json()["digest"]["timezone"] == "UTC"

    def test_persist(self, api):
        r = api.put("/api/settings", json={"digest": {"enabled": False, "hour": 7, "timezone": TZ}})
        assert r.status_code == 200
        assert r.json()["digest"] == {**r.json()["digest"], "enabled": False, "hour": 7, "timezone": TZ}
        d = api.get("/api/settings").json()["digest"]
        assert d["enabled"] is False and d["hour"] == 7 and d["timezone"] == TZ
        # partial update keeps other fields
        d2 = api.put("/api/settings", json={"digest": {"enabled": True}}).json()["digest"]
        assert d2["enabled"] is True and d2["hour"] == 7 and d2["timezone"] == TZ

    def test_send_now_empty(self, api):
        r = api.post("/api/settings/digest/send-now")
        assert r.status_code == 200
        assert r.json() == {"ok": True, "jobs": 0, "sent_to": None}


class TestDigestWithJobs:
    def test_create_board_app_and_send_now(self, api):
        assert api.put("/api/autopilot", json={"mode": "approval"}).status_code == 200
        tok = api.post("/api/boards/extension-token").json()["token"]
        STATE["tok"] = tok
        body = {"url": f"https://www.naukri.com/job-listings-test-digest-{TAG}", "title": "TEST_ Digest Data Analyst",
                "company": "TEST_ Digest Corp",
                "description": "Data Analyst with SQL, Python, Excel, Power BI, Tableau, dashboards and statistics."}
        d = requests.post(f"{BASE_URL}/api/ext/jobs", json=body, headers=ext(tok), timeout=30).json()
        STATE["opps"].append(d["opportunity_id"])
        st = None
        for _ in range(30):
            st = requests.get(f"{BASE_URL}/api/ext/jobs/{d['opportunity_id']}", headers=ext(tok), timeout=30).json()
            if st.get("application") or st.get("error"):
                break
            time.sleep(5)
        assert st.get("application"), st
        STATE["apps"].append(st["application"]["id"])
        assert st["application"]["status"] == "awaiting_approval"
        r = api.post("/api/settings/digest/send-now")
        assert r.status_code == 200
        j = r.json()
        assert j["ok"] is True and j["jobs"] == 1 and j["sent_to"] == "pilot-tester@applypilot.dev", j
        # send-now must not mark daily state
        assert "last_sent_date" not in digest_doc()


class TestDigestCron:
    def test_cron_auth(self):
        assert cron().status_code == 401
        assert cron({"Authorization": "Bearer wrong"}).status_code == 401

    def test_cron_duplicate_run_id(self):
        h = {"Authorization": f"Bearer {CRON}", "X-Webhook-Id": f"test-dup-{uuid.uuid4().hex}"}
        assert cron(h).json().get("accepted") == "board-digest"
        assert cron(h).json().get("duplicate") is True

    def test_wrong_hour_not_sent(self, api):
        local = datetime.now(ZoneInfo(TZ))
        other = (local.hour + 3) % 24
        api.put("/api/settings", json={"digest": {"enabled": True, "hour": other, "timezone": TZ}})
        MDB.app_settings.update_one({"user_id": uid()}, {"$unset": {"digest.last_sent_date": "", "digest.last_sent_at": ""}})
        cron_ok()
        assert "last_sent_date" not in digest_doc()

    def test_disabled_not_sent(self, api):
        local = datetime.now(ZoneInfo(TZ))
        api.put("/api/settings", json={"digest": {"enabled": False, "hour": local.hour, "timezone": TZ}})
        cron_ok()
        assert "last_sent_date" not in digest_doc()

    def test_matching_hour_sends_once_per_day(self, api):
        local = datetime.now(ZoneInfo(TZ))
        if local.minute >= 58:
            time.sleep(150)
            local = datetime.now(ZoneInfo(TZ))
        api.put("/api/settings", json={"digest": {"enabled": True, "hour": local.hour, "timezone": TZ}})
        cron_ok()
        d = digest_doc()
        assert d.get("last_sent_date") == local.date().isoformat(), d
        first = d["last_sent_at"]
        ev = MDB.application_events.find_one({"user_id": uid(), "type": "board_digest",
                                              "created_at": {"$gte": STATE["t0"]}})
        assert ev and "1 board jobs" in ev["detail"], ev
        cron_ok()
        assert digest_doc()["last_sent_at"] == first  # once per local day
        # GET settings exposes the stored date (shape check) and hour unchanged
        g = api.get("/api/settings").json()["digest"]
        assert g["hour"] == local.hour and g["timezone"] == TZ
