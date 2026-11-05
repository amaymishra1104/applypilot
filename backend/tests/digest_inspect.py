# Read-only helper: shows each user's digest settings + current UTC hour (no secrets printed)
from datetime import datetime, timezone

from dotenv import dotenv_values
from pymongo import MongoClient

env = dotenv_values("/app/backend/.env")
mdb = MongoClient(env["MONGO_URL"])[env["DB_NAME"]]
print("UTC now:", datetime.now(timezone.utc).isoformat())
for u in mdb.users.find({}, {"_id": 0, "user_id": 1, "email": 1}):
    s = mdb.app_settings.find_one({"user_id": u["user_id"]}, {"_id": 0, "digest": 1, "autopilot": 1})
    print(u["email"], u["user_id"], "settings_doc" if s else "NO_SETTINGS_DOC", (s or {}).get("digest"),
          ((s or {}).get("autopilot") or {}).get("paused"))
    print("   board waiting:", mdb.job_applications.count_documents(
        {"user_id": u["user_id"], "channel": "board", "status": {"$in": ["awaiting_approval", "draft"]}}))
