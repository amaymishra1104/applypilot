# Job Boards Auto-Apply: overview, extension token, apply profile, search config/run, browser-helper
# job save -> AI match -> board application lifecycle, emergency stop, Gmail guard, cross-user isolation.
import time
import uuid

import pytest
import requests

from conftest import BASE_URL

STATE = {"opps": [], "apps": [], "contacts": [], "orig_autopilot": None, "start": time.time()}
TAG = uuid.uuid4().hex[:8]


def ext(token):
    return {"X-ApplyPilot-Token": token}


def poll_job(token, opp_id, timeout=150):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        r = requests.get(f"{BASE_URL}/api/ext/jobs/{opp_id}", headers=ext(token), timeout=30)
        last = r.json()
        if last.get("application") or last.get("error"):
            return last
        time.sleep(5)
    return last


@pytest.fixture(scope="module", autouse=True)
def lifecycle(api):
    STATE["orig_autopilot"] = api.get("/api/autopilot").json()["autopilot"]
    yield
    # cleanup only what we created
    from dotenv import dotenv_values
    from pymongo import MongoClient
    env = dotenv_values("/app/backend/.env")
    mdb = MongoClient(env["MONGO_URL"])[env["DB_NAME"]]
    uid = mdb.users.find_one({"email": "pilot-tester@applypilot.dev"}, {"user_id": 1}) or {}
    for app_id in STATE["apps"]:
        mdb.job_applications.delete_one({"id": app_id})
    for oid in STATE["opps"]:
        mdb.job_applications.delete_many({"opportunity_id": oid, "user_id": uid.get("user_id")})
        mdb.job_matches.delete_many({"opportunity_id": oid, "user_id": uid.get("user_id")})
        api.delete(f"/api/opportunities/{oid}")
    for cid in STATE["contacts"]:
        api.delete(f"/api/contacts/{cid}")
    o = STATE["orig_autopilot"]
    api.put("/api/autopilot", json={"mode": o["mode"], "paused": False, "enabled": o["enabled"]})
    api.put("/api/boards/search-config", json={"enabled": False, "keywords": [], "boards": [], "max_new_per_run": 10})
    api.delete("/api/boards/extension-token")


class TestBoards:
    def test_overview_requires_auth(self):
        assert requests.get(f"{BASE_URL}/api/boards/overview", timeout=20).status_code == 401

    def test_overview_shape(self, api):
        d = api.get("/api/boards/overview").json()
        for k in ("boards", "extension", "apply_profile", "board_search", "applications", "runs", "autopilot"):
            assert k in d
        assert {"linkedin", "naukri", "indeed", "internshala", "wellfound", "instahyre"} <= set(d["boards"])

    def test_extension_token_rotation(self, api):
        t1 = api.post("/api/boards/extension-token").json()["token"]
        assert t1.startswith("apx_")
        me = requests.get(f"{BASE_URL}/api/ext/me", headers=ext(t1), timeout=20)
        assert me.status_code == 200
        assert me.json()["email"] == "pilot-tester@applypilot.dev"
        assert "apply_profile" in me.json() and "autopilot" in me.json()
        t2 = api.post("/api/boards/extension-token").json()["token"]
        assert requests.get(f"{BASE_URL}/api/ext/me", headers=ext(t1), timeout=20).status_code == 401
        assert requests.get(f"{BASE_URL}/api/ext/me", headers=ext(t2), timeout=20).status_code == 200
        ov = api.get("/api/boards/overview").json()
        assert ov["extension"] and "token_hash" not in ov["extension"]
        assert api.delete("/api/boards/extension-token").status_code == 200
        assert requests.get(f"{BASE_URL}/api/ext/me", headers=ext(t2), timeout=20).status_code == 401
        assert api.get("/api/boards/overview").json()["extension"] is None
        assert requests.get(f"{BASE_URL}/api/ext/me", timeout=20).status_code == 401
        assert requests.get(f"{BASE_URL}/api/ext/tasks", headers=ext("apx_bogus"), timeout=20).status_code == 401
        STATE["token"] = api.post("/api/boards/extension-token").json()["token"]

    def test_apply_profile(self, api):
        body = {"full_name": "TEST_ Pilot", "phone": "+91 99999 00000", "city": "Pune", "notice_period": "30 days",
                "custom_answers": [{"question": "Why us?", "answer": "Fit"}, {"question": "  ", "answer": "drop"}]}
        r = api.put("/api/boards/apply-profile", json=body)
        assert r.status_code == 200
        assert len(r.json()["custom_answers"]) == 1
        ap = api.get("/api/boards/overview").json()["apply_profile"]
        assert ap["full_name"] == "TEST_ Pilot" and ap["city"] == "Pune"
        assert ap["custom_answers"] == [{"question": "Why us?", "answer": "Fit"}]
        me = requests.get(f"{BASE_URL}/api/ext/me", headers=ext(STATE["token"]), timeout=20).json()
        assert me["apply_profile"]["phone"] == "+91 99999 00000"

    def test_search_config_validation(self, api):
        r = api.put("/api/boards/search-config", json={"enabled": False, "keywords": [" x "], "boards": ["bogus"],
                                                       "max_new_per_run": 99})
        d = r.json()
        assert d["boards"] == [] and d["max_new_per_run"] == 25 and d["keywords"] == ["x"]
        assert api.put("/api/boards/search-config", json={"max_new_per_run": 0}).json()["max_new_per_run"] == 1
        run = api.post("/api/boards/search/run")
        assert run.status_code == 400

    def test_ext_job_approval_flow(self, api):
        assert api.put("/api/autopilot", json={"mode": "approval"}).status_code == 200
        tok = STATE["token"]
        url = f"https://www.naukri.com/job-listings-test-data-analyst-{TAG}?src=x"
        hr = f"test_hr_{TAG}@acme-analytics.com"
        body = {"url": url, "title": "TEST_ Data Analyst", "company": "TEST_ Acme Analytics",
                "description": f"We need a Data Analyst skilled in SQL, Python, Excel, Power BI, Tableau and "
                               f"statistics to build dashboards. Send CV to {hr}."}
        r = requests.post(f"{BASE_URL}/api/ext/jobs", json=body, headers=ext(tok), timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["created"] is True
        opp_id = d["opportunity_id"]
        STATE["opps"].append(opp_id)
        dup = requests.post(f"{BASE_URL}/api/ext/jobs", json={**body, "url": url.split("?")[0]},
                            headers=ext(tok), timeout=30).json()
        assert dup["created"] is False and dup["opportunity_id"] == opp_id
        opp = api.get(f"/api/opportunities/{opp_id}").json()
        assert opp.get("board") == "naukri" and opp.get("source") == "browser_helper"
        contacts = api.get("/api/contacts", params={"search": hr}).json()
        items = contacts if isinstance(contacts, list) else contacts.get("items", contacts.get("contacts", []))
        match = [c for c in items if c.get("hr_email") == hr]
        assert match, f"HR contact not created: {str(contacts)[:300]}"
        STATE["contacts"].append(match[0]["id"])
        st = poll_job(tok, opp_id)
        assert st and st.get("application"), f"no application: {st}"
        assert st["match"]["score"] is not None
        app = st["application"]
        STATE["apps"].append(app["id"])
        STATE["app1"] = app["id"]
        assert app["status"] == "awaiting_approval"
        assert app["board"] == "naukri" and app["body_text"]
        ov = api.get("/api/boards/overview").json()
        card = [a for a in ov["applications"] if a["id"] == app["id"]][0]
        assert card["has_hr_email"] is True

    def test_gmail_send_guard(self, api):
        r = api.post(f"/api/applications/{STATE['app1']}/send")
        assert r.status_code == 400
        assert "browser helper" in r.json()["detail"]

    def test_isolation(self, api2):
        aid, oid = STATE["app1"], STATE["opps"][0]
        assert api2.get(f"/api/applications/{aid}").status_code == 404
        assert api2.post(f"/api/applications/{aid}/approve").status_code == 404
        assert all(a["id"] != aid for a in api2.get("/api/boards/overview").json()["applications"])
        t2 = api2.post("/api/boards/extension-token").json()["token"]
        try:
            assert requests.get(f"{BASE_URL}/api/ext/jobs/{oid}", headers=ext(t2), timeout=20).status_code == 404
            assert requests.post(f"{BASE_URL}/api/ext/applications/{aid}/result", json={"outcome": "submitted"},
                                 headers=ext(t2), timeout=20).status_code == 404
            assert requests.get(f"{BASE_URL}/api/ext/me", headers=ext(t2), timeout=20).json()["email"] == \
                "pilot-second@applypilot.dev"
            tasks = requests.get(f"{BASE_URL}/api/ext/tasks", headers=ext(t2), timeout=20).json()["tasks"]
            assert all(t["id"] != aid for t in tasks)
        finally:
            api2.delete("/api/boards/extension-token")

    def test_approve_task_submit(self, api):
        aid, tok = STATE["app1"], STATE["token"]
        assert api.post(f"/api/applications/{aid}/approve").status_code == 200
        assert api.get(f"/api/applications/{aid}").json()["status"] == "approved"
        tasks = requests.get(f"{BASE_URL}/api/ext/tasks", headers=ext(tok), timeout=20).json()
        assert tasks["tasks"] and tasks["tasks"][0]["id"] == aid, tasks
        assert api.get(f"/api/applications/{aid}").json()["status"] == "submitting"
        ctx = requests.get(f"{BASE_URL}/api/ext/context", params={"url": tasks["tasks"][0]["job_url"]},
                           headers=ext(tok), timeout=20).json()
        assert ctx["application"]["id"] == aid and ctx["resume"]["version_id"]
        pdf = requests.get(f"{BASE_URL}/api/ext/resume/{ctx['resume']['version_id']}", headers=ext(tok), timeout=30)
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
        r = requests.post(f"{BASE_URL}/api/ext/applications/{aid}/result", json={"outcome": "submitted"},
                          headers=ext(tok), timeout=20)
        assert r.status_code == 200
        a = api.get(f"/api/applications/{aid}").json()
        assert a["status"] == "sent" and a["sent_at"]
        bad = requests.post(f"{BASE_URL}/api/ext/applications/{aid}/result", json={"outcome": "weird"},
                            headers=ext(tok), timeout=20)
        assert bad.status_code == 409  # status guard runs before outcome validation

    def test_auto_mode_needs_attention_retry(self, api):
        assert api.put("/api/autopilot", json={"mode": "auto", "min_match_score": 0}).status_code == 200
        tok = STATE["token"]
        url = f"https://www.linkedin.com/jobs/view/test-{TAG}/"
        body = {"url": url, "title": "TEST_ Senior Data Analyst", "company": "TEST_ Beta Corp",
                "description": "Data Analyst with SQL, Python, Power BI, dashboards and reporting."}
        d = requests.post(f"{BASE_URL}/api/ext/jobs", json=body, headers=ext(tok), timeout=30).json()
        STATE["opps"].append(d["opportunity_id"])
        st = poll_job(tok, d["opportunity_id"])
        api.put("/api/autopilot", json={"min_match_score": STATE["orig_autopilot"]["min_match_score"]})
        assert st and st.get("application"), st
        aid = st["application"]["id"]
        STATE["apps"].append(aid)
        assert st["application"]["status"] == "queued_auto"
        # result is only accepted while 'submitting' (iteration 4 fix)
        early = requests.post(f"{BASE_URL}/api/ext/applications/{aid}/result",
                              json={"outcome": "needs_attention"}, headers=ext(tok), timeout=20)
        assert early.status_code == 409
        from dotenv import dotenv_values
        from pymongo import MongoClient
        env = dotenv_values("/app/backend/.env")
        MongoClient(env["MONGO_URL"])[env["DB_NAME"]].job_applications.update_one(
            {"id": aid}, {"$set": {"status": "submitting", "previous_status": "queued_auto"}})
        r = requests.post(f"{BASE_URL}/api/ext/applications/{aid}/result",
                          json={"outcome": "needs_attention", "detail": "Captcha on page"}, headers=ext(tok), timeout=20)
        assert r.status_code == 200
        a = api.get(f"/api/applications/{aid}").json()
        assert a["status"] == "needs_attention" and a["error"] == "Captcha on page"
        assert api.post(f"/api/applications/{aid}/retry").status_code == 200
        assert api.get(f"/api/applications/{aid}").json()["status"] == "approved"
        STATE["app2"] = aid

    def test_emergency_stop(self, api):
        tok = STATE["token"]
        assert api.post("/api/autopilot/emergency-stop").status_code == 200
        try:
            t = requests.get(f"{BASE_URL}/api/ext/tasks", headers=ext(tok), timeout=20).json()
            assert t["tasks"] == [] and "stop" in t["reason"].lower()
            assert api.get(f"/api/applications/{STATE['app2']}").json()["status"] == "approved"
        finally:
            r = api.put("/api/autopilot", json={"paused": False})
            assert r.json()["autopilot"]["paused"] is False
        t = requests.get(f"{BASE_URL}/api/ext/tasks", headers=ext(tok), timeout=20).json()
        assert t["tasks"] and t["tasks"][0]["id"] == STATE["app2"]

    def test_board_search_run(self, api):
        boards = ["linkedin", "naukri", "indeed", "internshala", "wellfound", "instahyre", "remotive"]
        cfg = api.put("/api/boards/search-config", json={"enabled": False, "keywords": ["data analyst"],
                                                         "location": "", "boards": boards,
                                                         "max_new_per_run": 2}).json()
        assert cfg["boards"] == boards
        before = {r["id"] for r in api.get("/api/boards/overview").json()["runs"]}
        r = api.post("/api/boards/search/run")
        assert r.status_code == 200 and r.json().get("started") is True
        assert api.post("/api/boards/search/run").status_code == 409
        run = None
        end = time.time() + 240
        while time.time() < end:
            runs = [x for x in api.get("/api/boards/overview").json()["runs"] if x["id"] not in before]
            if runs and runs[0]["status"] == "done":
                run = runs[0]
                break
            time.sleep(10)
        # record created opps for cleanup
        for o in api.get("/api/opportunities").json() if isinstance(api.get("/api/opportunities").json(), list) else []:
            if o.get("source") == "board_search" and o.get("id") not in STATE["opps"]:
                STATE["opps"].append(o["id"])
        for c in api.get("/api/contacts").json():
            if c.get("notes") == "Found in a job board posting" and c["id"] not in STATE["contacts"] \
                    and (c.get("created_at") or "") >= time.strftime("%Y-%m-%dT%H:%M", time.gmtime(STATE["start"])):
                STATE["contacts"].append(c["id"])
        STATE["run"] = run
        print("RUN:", run)
        assert run, "search run did not finish in 240s"
        assert set(run["boards"]) == set(boards)
        assert run["new_jobs"] <= 2
        found = {b: s["found"] for b, s in run["boards"].items()}
        errors = {b: s["error"] for b, s in run["boards"].items() if s["error"]}
        print("FOUND", found, "ERRORS", errors)
        assert sum(found.values()) > 0
