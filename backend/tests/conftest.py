# Shared fixtures: Clerk Backend API session tokens for the two test accounts
import os
import time

import pytest
import requests
from dotenv import dotenv_values

FRONT_ENV = dotenv_values("frontend/.env") or dotenv_values("/app/frontend/.env") or {}
BASE_URL = (FRONT_ENV.get("REACT_APP_BACKEND_URL") or "http://localhost:8000").rstrip("/")
BACK_ENV = dotenv_values("backend/.env") or dotenv_values("/app/backend/.env") or {}
_SK = BACK_ENV.get("CLERK_SECRET_KEY")
CLERK = "https://api.clerk.com/v1"
PRIMARY = "pilot-tester@applypilot.dev"
SECOND = "pilot-second@applypilot.dev"


class ClerkSession:
    def __init__(self, email):
        h = {"Authorization": f"Bearer {_SK}"}
        users = requests.get(f"{CLERK}/users", params={"email_address": email}, headers=h, timeout=20).json()
        if not users:
            pytest.skip(f"Clerk user {email} missing")
        self.uid = users[0]["id"]
        s = requests.post(f"{CLERK}/sessions", json={"user_id": self.uid}, headers=h, timeout=20)
        s.raise_for_status()
        self.sid = s.json()["id"]
        self._h = h
        self._tok, self._t = None, 0

    def token(self):
        if not self._tok or time.time() - self._t > 40:
            r = requests.post(f"{CLERK}/sessions/{self.sid}/tokens", json={"expires_in_seconds": 600},
                              headers=self._h, timeout=20)
            r.raise_for_status()
            self._tok, self._t = r.json()["jwt"], time.time()
        return self._tok


class Api:
    def __init__(self, sess):
        self.sess = sess
        self.s = requests.Session()

    def req(self, method, path, **kw):
        headers = {"Authorization": f"Bearer {self.sess.token()}", **kw.pop("headers", {})}
        return self.s.request(method, f"{BASE_URL}{path}", headers=headers, timeout=60, **kw)

    get = lambda self, p, **k: self.req("GET", p, **k)
    post = lambda self, p, **k: self.req("POST", p, **k)
    put = lambda self, p, **k: self.req("PUT", p, **k)
    delete = lambda self, p, **k: self.req("DELETE", p, **k)


@pytest.fixture(scope="session")
def api():
    return Api(ClerkSession(PRIMARY))


@pytest.fixture(scope="session")
def api2():
    return Api(ClerkSession(SECOND))
