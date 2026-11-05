#!/usr/bin/env python3
"""Password hashing utility for ApplyPilot owner login.
Usage:
    python scripts/hash_password.py [password]
    python scripts/hash_password.py --verify <password> <hash>
"""
import sys
import getpass
import bcrypt


def hash_password(password: str) -> str:
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--verify":
        if len(sys.argv) < 4:
            print("Usage: python scripts/hash_password.py --verify <password> <hash>", file=sys.stderr)
            sys.exit(1)
        ok = verify_password(sys.argv[2], sys.argv[3])
        print("MATCH" if ok else "NO MATCH")
        sys.exit(0 if ok else 1)

    if len(sys.argv) > 1:
        pwd = sys.argv[1]
    else:
        pwd = getpass.getpass("Enter password to hash: ")
        confirm = getpass.getpass("Confirm password: ")
        if pwd != confirm:
            print("Error: Passwords do not match", file=sys.stderr)
            sys.exit(1)

    if not pwd:
        print("Error: Password cannot be empty", file=sys.stderr)
        sys.exit(1)

    hashed = hash_password(pwd)
    print("\nBcrypt hash:")
    print(hashed)
    print("\nAdd this to your backend/.env as:")
    print(f"OWNER_PASSWORD_HASH={hashed}")


if __name__ == "__main__":
    main()
