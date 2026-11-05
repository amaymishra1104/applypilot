# Iteration 4 retest: ext result 409 guard, ext resume 200, switch-to-email endpoint, search budget stop.
import time
import uuid

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

from conftest import BASE_URL

TAG = uuid.uuid4().hex[:8]
S = {"opps": [], "apps": [], "contacts": [], "start": time.time()}


def ext(t):
    return {"X-ApplyPilot-Token": t}


def mdb():
    env = dotenv_values("/app/backend/.env")
    return MongoClient(env["MONGO_URL"])[env["DB_NAME"]]


def poll(tok, oid, timeout=150):
    end, last = time.time() + timeout, None
    while time.time() < end:
        last = requests.get(f"{BASE_URL}/api/ext/jobs/{oid}", headers=ext(tok), timeout=30).json()
        if last.get("application") or last.get("error"):
            return last
        time.sleep(5)
    return last


@pytest.fixture(scope="module", autouse=True)
def life(api):
    S["orig"] = api.get("/api/autopilot").json()["autopilot"]
    api.put("/api/autopilot", json={"mode": "approval"})
    S["tok"] = api.post("/api/boards/extension-token").json()["token"]
    yield
    db = mdb()
    uid = (db.users.find_one({"email": "pilot-tester@applypilot.dev"}, {"user_id": 1}) or {}).get("user_id")
    for a in S["apps"]:
        db.job_applications.delete_one({"id": a, "user_id": uid})
    for o in S["opps"]:
        db.job_applications.delete_many({"opportunity_id": o, "user_id": uid})
        db.job_matches.delete_many({"opportunity_id": o, "user_id": uid})
        api.delete(f"/api/opportunities/{o}")
    for c in S["contacts"]:
        api.delete(f"/api/contacts/{c}")
    o = S["orig"]
    api.put("/api/autopilot", json={"mode": o["mode"], "paused": False, "enabled": o["enabled"]})
    api.put("/api/boards/search-config", json={"enabled": False, "keywords": [], "boards": [], "max_new_per_run": 10})
    api.delete("/api/boards/extension-token")


class TestFixes:
    def test_switch_to_email(self, api):
        tok = S["tok"]
        hr = f"test_hr_{TAG}@gamma-test.com"
        d = requests.post(f"{BASE_URL}/api/ext/jobs", headers=ext(tok), timeout=30, json={
            "url": f"https://www.naukri.com/job-listings-test-analyst-{TAG}", "title": "TEST_ Data Analyst",
            "company": "TEST_ Gamma Corp",
            "description": f"Data Analyst with SQL, Python, Power BI, Excel dashboards. Mail {hr}."}).json()
        S["opps"].append(d["opportunity_id"])
        cs = api.get("/api/contacts", params={"search": hr}).json()
        cs = cs if isinstance(cs, list) else cs.get("items", [])
        S["contacts"] += [c["id"] for c in cs if c.get("hr_email") == hr]
        st = poll(tok, d["opportunity_id"])
        assert st and st.get("application"), st
        aid = st["application"]["id"]
        S["apps"].append(aid)
        assert st["application"]["status"] == "awaiting_approval"
        # 409 guard: not submitting
        r = requests.post(f"{BASE_URL}/api/ext/applications/{aid}/result", json={"outcome": "submitted"},
                          headers=ext(tok), timeout=20)
        assert r.status_code == 409, r.text
        assert api.get(f"/api/applications/{aid}").json()["status"] == "awaiting_approval"
        sw = api.post(f"/api/boards/applications/{aid}/switch-to-email")
        assert sw.status_code == 200, sw.text
        em = sw.json()
        S["apps"].append(em["id"])
        print("EMAIL APP", {k: em.get(k) for k in ("id", "channel", "status", "hr_email")})
        assert em["id"] != aid and em.get("channel") != "board" and em.get("hr_email") == hr
        assert api.get(f"/api/applications/{aid}").json()["status"] == "cancelled"
        assert api.post(f"/api/boards/applications/{aid}/switch-to-email").status_code == 400
        ov = api.get("/api/boards/overview").json()
        assert [a for a in ov["applications"] if a["id"] == aid][0]["status"] == "cancelled"

    def test_approve_task_result_guard(self, api):
        tok = S["tok"]
        d = requests.post(f"{BASE_URL}/api/ext/jobs", headers=ext(tok), timeout=30, json={
            "url": f"https://www.linkedin.com/jobs/view/test-fix-{TAG}/", "title": "TEST_ BI Analyst",
            "company": "TEST_ Delta Corp", "description": "Data Analyst SQL Python Power BI reporting."}).json()
        S["opps"].append(d["opportunity_id"])
        st = poll(tok, d["opportunity_id"])
        assert st and st.get("application"), st
        aid = st["application"]["id"]
        S["apps"].append(aid)
        assert api.post(f"/api/applications/{aid}/approve").status_code == 200
        tasks = requests.get(f"{BASE_URL}/api/ext/tasks", headers=ext(tok), timeout=20).json()
        assert tasks["tasks"] and tasks["tasks"][0]["id"] == aid, tasks
        # switching while submitting is refused
        assert api.post(f"/api/boards/applications/{aid}/switch-to-email").status_code == 400
        t0 = time.time()
        pdf = requests.get(f"{BASE_URL}/api/ext/resume/{st['application']['resume_version_id']}",
                           headers=ext(tok), timeout=40)
        print("resume", pdf.status_code, round(time.time() - t0, 2))
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
        assert requests.get(f"{BASE_URL}/api/ext/resume/nonexistent", headers=ext(tok), timeout=20).status_code == 404
        r = requests.post(f"{BASE_URL}/api/ext/applications/{aid}/result", json={"outcome": "submitted"},
                          headers=ext(tok), timeout=20)
        assert r.status_code == 200
        assert api.get(f"/api/applications/{aid}").json()["status"] == "sent"
        again = requests.post(f"{BASE_URL}/api/ext/applications/{aid}/result", json={"outcome": "needs_attention"},
                              headers=ext(tok), timeout=20)
        assert again.status_code == 409
        assert api.get(f"/api/applications/{aid}").json()["status"] == "sent"
        assert api.post(f"/api/boards/applications/{aid}/switch-to-email").status_code == 400

    def test_search_budget_stops(self, api):
        boards = ["remotive", "internshala", "wellfound"]
        api.put("/api/boards/search-config", json={"enabled": False, "keywords": ["data analyst"], "location": "",
                                                    "boards": boards, "max_new_per_run": 1})
        before = {r["id"] for r in api.get("/api/boards/overview").json()["runs"]}
        db = mdb()
        uid = db.users.find_one({"email": "pilot-tester@applypilot.dev"}, {"user_id": 1})["user_id"]
        before_opps = {o["id"] for o in db.job_opportunities.find({"user_id": uid}, {"id": 1})}
        t0 = time.time()
        assert api.post("/api/boards/search/run").status_code == 200
        run, end = None, time.time() + 200
        while time.time() < end:
            rs = [x for x in api.get("/api/boards/overview").json()["runs"] if x["id"] not in before]
            if rs and rs[0]["status"] == "done":
                run = rs[0]
                break
            time.sleep(5)
        for o in db.job_opportunities.find({"user_id": uid, "source": "board_search"}, {"id": 1}):
            if o["id"] not in before_opps:
                S["opps"].append(o["id"])
        print("RUN", run, "secs", round(time.time() - t0, 1))
        assert run
        assert run["new_jobs"] <= 1
        if run["new_jobs"] == 1:
            names = list(run["boards"])
            hit = [b for b, s in run["boards"].items() if s["new"] == 1][0]
            assert names[-1] == hit, f"boards after budget used should not appear: {names}"
