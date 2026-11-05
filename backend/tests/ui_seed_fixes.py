# UI retest helper: seeds one TEST_ board app (awaiting_approval, with HR email) and prints a Clerk sign-in ticket.
import json
import sys
import time
import uuid

import requests
from dotenv import dotenv_values

sys.path.insert(0, "/app/backend/tests")
from conftest import BASE_URL, CLERK, PRIMARY, Api, ClerkSession, _SK  # noqa

api = Api(ClerkSession(PRIMARY))
out = {"orig": api.get("/api/autopilot").json()["autopilot"]}
api.put("/api/autopilot", json={"mode": "approval"})
tok = api.post("/api/boards/extension-token").json()["token"]
tag = uuid.uuid4().hex[:8]
hr = f"test_hr_ui_{tag}@epsilon-test.com"
d = requests.post(f"{BASE_URL}/api/ext/jobs", headers={"X-ApplyPilot-Token": tok}, timeout=30, json={
    "url": f"https://www.naukri.com/job-listings-test-ui-{tag}", "title": "TEST_UI Data Analyst",
    "company": "TEST_UI Epsilon", "description": f"Data Analyst SQL Python Power BI. Mail {hr}."}).json()
out["opp"] = d["opportunity_id"]
for _ in range(30):
    st = requests.get(f"{BASE_URL}/api/ext/jobs/{d['opportunity_id']}", headers={"X-ApplyPilot-Token": tok},
                      timeout=30).json()
    if st.get("application") or st.get("error"):
        break
    time.sleep(5)
out["app"] = (st.get("application") or {}).get("id")
cs = api.get("/api/contacts", params={"search": hr}).json()
out["contacts"] = [c["id"] for c in (cs if isinstance(cs, list) else []) if c.get("hr_email") == hr]
api.delete("/api/boards/extension-token")
t = requests.post(f"{CLERK}/sign_in_tokens", json={"user_id": api.sess.uid, "expires_in_seconds": 1800},
                  headers={"Authorization": f"Bearer {_SK}"}, timeout=20).json()
out["ticket"] = t["token"]
json.dump(out, open("/tmp/ui_seed.json", "w"))
print({k: v for k, v in out.items() if k != "ticket"}, "TICKET:", out["ticket"])
