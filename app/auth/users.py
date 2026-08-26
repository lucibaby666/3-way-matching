"""
User store backed by a local JSON file.

The file layout (default ``users.json`` in the repository
root, overridable via the ``USERS_FILE`` env var):

    {
      "users": [
        {
          "username": "admin",
          "role": "ADMIN",
          "password_hash": "pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>"
        }
      ]
    }

Password hashes use PBKDF2-HMAC-SHA256 from the Python
standard library. Generate a new hash with:

    python -m app.auth.users <plaintext-password>
"""

import hashlib
import json
import logging
import secrets
from pathlib import Path
from typing import Dict, List, Optional

from app.env import get_env
from app.monitoring.json_logging import log_event

logger = logging.getLogger(__name__)

DEFAULT_USERS_FILE = (
    Path(__file__).resolve().parent.parent.parent / "users.json"
)

PBKDF2_ITERATIONS = 390000

VALID_ROLES = {"ADMIN", "AUDIT"}


class UserAccount:
    def __init__(self, username: str, role: str):
        self.username = username
        self.role = role

    def to_dict(self) -> Dict[str, str]:
        return {
            "username": self.username,
            "role": self.role,
        }


def get_users_file() -> Path:
    configured = get_env("USERS_FILE")

    if configured:
        return Path(configured)

    return DEFAULT_USERS_FILE


def load_users() -> List[Dict[str, str]]:
    path = get_users_file()

    if not path.exists():
        log_event(
            logger,
            "users_file_missing",
            level=logging.ERROR,
            path=str(path),
        )
        return []

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        log_event(
            logger,
            "users_file_read_failed",
            level=logging.ERROR,
            error_type=exc.__class__.__name__,
            error_message=str(exc),
        )
        return []

    users = [
        user
        for user in payload.get("users", [])
        if user.get("username")
        and user.get("password_hash")
    ]

    for user in users:
        user.setdefault("role", "AUDIT")

    return users


def find_user(username: str) -> Optional[Dict[str, str]]:
    for user in load_users():
        if user["username"] == username:
            return user

    return None


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt.encode(),
        PBKDF2_ITERATIONS,
    ).hex()

    return (
        f"pbkdf2_sha256${PBKDF2_ITERATIONS}"
        f"${salt}${digest}"
    )


def verify_password(
    password: str, stored_hash: str
) -> bool:
    parts = stored_hash.split("$")

    if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
        return False

    try:
        iterations = int(parts[1])
    except ValueError:
        return False

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        parts[2].encode(),
        iterations,
    ).hex()

    return secrets.compare_digest(digest, parts[3])


def authenticate(
    username: str, password: str
) -> Optional[UserAccount]:
    """
    Return the user account when credentials match,
    otherwise ``None``. A dummy verification is run for
    unknown usernames to keep response timing uniform.
    """

    user = find_user(username)
    stored_hash = (
        user["password_hash"]
        if user
        else hash_password(password)
    )

    if not verify_password(password, stored_hash):
        return None

    if user is None:
        return None

    role = str(user["role"]).upper()

    if role not in VALID_ROLES:
        return None

    return UserAccount(
        username=user["username"],
        role=role,
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print(
            "Usage: python -m app.auth.users "
            "<plaintext-password>"
        )
        raise SystemExit(1)

    print(hash_password(sys.argv[1]))
