# Restores pilot-tester digest settings to enabled=true hour=8 tz=UTC and autopilot paused=false
import sys
sys.path.insert(0, "/app/backend/tests")
from conftest import PRIMARY, Api, ClerkSession  # noqa
api = Api(ClerkSession(PRIMARY))
print(api.put("/api/settings", json={"digest": {"enabled": True, "hour": 8, "timezone": "UTC"}}).json()["digest"])
print(api.put("/api/autopilot", json={"paused": False}).json()["autopilot"])
