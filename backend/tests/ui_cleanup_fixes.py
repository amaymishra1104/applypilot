# Cleanup for ui_seed_fixes.py: deletes only seeded ids (+ apps on that opportunity) and restores autopilot.
import json
import sys

from dotenv import dotenv_values
from pymongo import MongoClient

sys.path.insert(0, "/app/backend/tests")
from conftest import PRIMARY, Api, ClerkSession  # noqa

s = json.load(open("/tmp/ui_seed.json"))
api = Api(ClerkSession(PRIMARY))
env = dotenv_values("/app/backend/.env")
db = MongoClient(env["MONGO_URL"])[env["DB_NAME"]]
uid = db.users.find_one({"email": PRIMARY}, {"user_id": 1})["user_id"]
print("apps", db.job_applications.delete_many({"opportunity_id": s["opp"], "user_id": uid}).deleted_count)
print("matches", db.job_matches.delete_many({"opportunity_id": s["opp"], "user_id": uid}).deleted_count)
print("opp", api.delete(f"/api/opportunities/{s['opp']}").status_code)
for c in s["contacts"]:
    print("contact", api.delete(f"/api/contacts/{c}").status_code)
o = s["orig"]
api.put("/api/autopilot", json={"mode": o["mode"], "paused": False, "enabled": o["enabled"],
                                "min_match_score": o["min_match_score"]})
print(api.get("/api/autopilot").json()["autopilot"])
ov = api.get("/api/boards/overview").json()
print("board apps left", len(ov["applications"]), "ext", ov["extension"], "search", ov["board_search"])
