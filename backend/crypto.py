import os

from cryptography.fernet import Fernet


def validate_encryption_key() -> None:
    """Validate that APP_ENCRYPTION_KEY is set and valid.
    Fails startup if missing or malformed to avoid silent plaintext fallback."""
    key = os.environ.get("APP_ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "APP_ENCRYPTION_KEY is required and missing from environment! "
            "Generate one using: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    try:
        Fernet(key.encode())
    except Exception as exc:
        raise RuntimeError(f"Invalid APP_ENCRYPTION_KEY: {exc}")


def _fernet() -> Fernet:
    key = os.environ.get("APP_ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError("APP_ENCRYPTION_KEY is not configured")
    try:
        return Fernet(key.encode())
    except Exception as exc:
        raise RuntimeError(f"Invalid APP_ENCRYPTION_KEY: {exc}")


def encrypt(value: str) -> str:
    if not value:
        return ""
    f = _fernet()
    return f.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    if not value:
        return ""
    f = _fernet()
    try:
        return f.decrypt(value.encode()).decode()
    except Exception as exc:
        raise ValueError(f"Decryption failed: {exc}")

