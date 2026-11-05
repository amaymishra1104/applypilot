import os

from cryptography.fernet import Fernet


def _fernet() -> Fernet | None:
    key = os.environ.get("APP_ENCRYPTION_KEY", "")
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except Exception:
        return None


def encrypt(value: str) -> str:
    f = _fernet()
    if not f or not value:
        return value
    return f.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    f = _fernet()
    if not f or not value:
        return value
    try:
        return f.decrypt(value.encode()).decode()
    except Exception:
        return value
