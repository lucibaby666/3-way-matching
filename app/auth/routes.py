"""
Authentication endpoints.

    POST /api/auth/login    -> set session cookie
    POST /api/auth/logout   -> clear session cookie
    GET  /api/auth/me       -> current user (username + role)
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.dependencies import (
    SESSION_COOKIE,
    SESSION_TTL_SECONDS,
    create_session,
    delete_session,
    get_current_user,
)
from app.auth.users import UserAccount, authenticate
from app.monitoring.json_logging import log_event

router = APIRouter(
    prefix="/api/auth",
    tags=["auth"],
)

logger = logging.getLogger(__name__)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


@router.post("/login")
async def login(request: LoginRequest) -> JSONResponse:
    user = await asyncio.to_thread(
        authenticate, request.username, request.password
    )

    if user is None:
        log_event(
            logger,
            "login_failed",
            level=logging.WARNING,
            username=request.username,
        )
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password.",
        )

    token = create_session(user)

    log_event(
        logger,
        "user_logged_in",
        username=user.username,
        role=user.role,
    )

    response = JSONResponse(user.to_dict())
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
    )

    return response


@router.post("/logout")
async def logout(request: Request) -> JSONResponse:
    delete_session(request.cookies.get(SESSION_COOKIE))

    log_event(
        logger,
        "user_logged_out",
    )

    response = JSONResponse({"status": "logged_out"})
    response.delete_cookie(key=SESSION_COOKIE)

    return response


@router.get("/me")
async def me(
    user: UserAccount = Depends(get_current_user),
) -> dict:
    return user.to_dict()
