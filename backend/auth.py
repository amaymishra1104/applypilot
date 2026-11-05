import os
import time
import asyncio
import re
import bcrypt
import jwt
from fastapi import HTTPException

OWNER_USER_ID = "owner"
COOKIE_NAME = "applypilot_session"
SESSION_EXPIRY_SECONDS = 7 * 86400  # 7 days
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_WINDOW_SECONDS = 900  # 15 minutes

# In-memory tracking for login attempts with lock
_login_lock = asyncio.Lock()
_failed_attempts: list[float] = []


def get_owner_email() -> str:
    return os.environ.get("OWNER_EMAIL", "").strip().lower()


def get_owner_password_hash() -> str:
    return os.environ.get("OWNER_PASSWORD_HASH", "").strip()


def get_session_secret() -> str:
    return os.environ.get("SESSION_SECRET", "").strip()


def is_secure_cookie() -> bool:
    env = os.environ.get("ENV", "development").lower()
    explicit = os.environ.get("SECURE_COOKIES", "").lower()
    if explicit in ("true", "1", "yes"):
        return True
    if explicit in ("false", "0", "no"):
        return False
    return env == "production"


def validate_owner_config():
    """Verify OWNER_EMAIL, OWNER_PASSWORD_HASH, and SESSION_SECRET on startup.
    Fails startup if not configured properly."""
    email = get_owner_email()
    pwd_hash = get_owner_password_hash()
    secret = get_session_secret()

    missing = []
    if not email or "@" not in email:
        missing.append("OWNER_EMAIL")
    if not pwd_hash or not pwd_hash.startswith("$2"):
        missing.append("OWNER_PASSWORD_HASH (valid bcrypt hash starting with $2)")
    if not secret or len(secret) < 16:
        missing.append("SESSION_SECRET (min 16 chars)")

    if missing:
        msg = f"Owner authentication configuration error! Missing or invalid: {', '.join(missing)}."
        raise RuntimeError(msg)


def create_session_token(email: str) -> str:
    secret = get_session_secret()
    if not secret:
        raise RuntimeError("SESSION_SECRET is not configured")
    now = int(time.time())
    payload = {
        "sub": OWNER_USER_ID,
        "email": email,
        "iat": now,
        "exp": now + SESSION_EXPIRY_SECONDS,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def verify_session_token(token: str) -> dict:
    secret = get_session_secret()
    if not secret:
        raise HTTPException(status_code=500, detail="SESSION_SECRET is not configured")
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid session token.")


async def check_login_lockout():
    now = time.time()
    cutoff = now - LOCKOUT_WINDOW_SECONDS
    async with _login_lock:
        # Purge stale attempts
        while _failed_attempts and _failed_attempts[0] < cutoff:
            _failed_attempts.pop(0)

        if len(_failed_attempts) >= MAX_FAILED_ATTEMPTS:
            oldest = _failed_attempts[0]
            remaining = int(LOCKOUT_WINDOW_SECONDS - (now - oldest))
            mins = max(1, remaining // 60 + (1 if remaining % 60 else 0))
            raise HTTPException(
                status_code=429,
                detail=f"Too many failed login attempts. Account temporarily locked. Please try again in {mins} minutes.",
            )


async def record_login_failure():
    async with _login_lock:
        _failed_attempts.append(time.time())


async def record_login_success():
    async with _login_lock:
        _failed_attempts.clear()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False
