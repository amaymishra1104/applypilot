# Prints a Clerk sign-in ticket for pilot-tester (UI tests via /sign-in?__clerk_ticket=)
import sys

import requests

sys.path.insert(0, "/app/backend/tests")
from conftest import CLERK, PRIMARY, _SK  # noqa

h = {"Authorization": f"Bearer {_SK}"}
uid = requests.get(f"{CLERK}/users", params={"email_address": PRIMARY}, headers=h, timeout=20).json()[0]["id"]
t = requests.post(f"{CLERK}/sign_in_tokens", json={"user_id": uid, "expires_in_seconds": 1800}, headers=h, timeout=20).json()
print(t["token"])
