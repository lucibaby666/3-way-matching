"""
Session management and role-based dependencies.

Sessions are held in memory (a signed cookie alternative
would be needed for multi-replica deployments) and the
browser receives an HTTP-only session cookie.
"""

import secrets
import threading
from typing import Dict, Optional, Set

from fastapi import Depends, HTTPException, Request, status

from app.auth.users import UserAccount

SESSION_COOKIE = "tm_session"
SESSION_TTL_SECONDS = 8 * 60 * 60

_lock = threading.Lock()
_sessions: Dict[str, Dict[str, str]] = {}


def create_session(user: UserAccount) -> str:
    token = secrets.token_urlsafe(32)

    with _lock:
        _sessions[token] = user.to_dict()

    return token


def get_session(token: Optional[str]) -> Optional[UserAccount]:
    if not token:
        return None

    with _lock:
        record = _sessions.get(token)

        if record is None:
            return None

        return UserAccount(
            username=record["username"],
            role=record["role"],
        )


def delete_session(token: Optional[str]) -> None:
    if not token:
        return

    with _lock:
        _sessions.pop(token, None)


def get_current_user(
    request: Request,
) -> UserAccount:
    user = get_session(request.cookies.get(SESSION_COOKIE))

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    return user


def require_any_role(*roles: Set[str]):
    allowed = {role.upper() for role in roles}

    def dependency(
        user: UserAccount = Depends(get_current_user),
    ) -> UserAccount:
        if allowed and user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "This endpoint requires one of the "
                    f"following roles: {sorted(allowed)}."
                ),
            )

        return user

    return dependency


require_authenticated = require_any_role()
require_admin = require_any_role("ADMIN")
require_admin_or_audit = require_any_role("ADMIN", "AUDIT")
