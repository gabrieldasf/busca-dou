"""Authentication web routes - login, signup, logout, dashboard."""

from __future__ import annotations

import secrets
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.deps import hash_api_key
from src.app.database import get_session
from src.models.api_key import ApiKey
from src.models.user import User
from src.services.auth import (
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    create_session_token,
    create_user,
    decode_session_token,
    get_user_by_email,
    get_user_by_id,
    verify_password,
)

templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

router = APIRouter(tags=["auth"])


async def get_current_user(
    request: Request,
    session: AsyncSession,
) -> User | None:
    """Extract user from session cookie. Returns None if not authenticated."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    user_id = decode_session_token(token)
    if user_id is None:
        return None
    return await get_user_by_id(session, user_id)


def _set_session_cookie(response: RedirectResponse, user: User) -> RedirectResponse:
    token = create_session_token(user.id)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return response


# --- Pages ---


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "auth/login.html", {"error": None})


@router.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "auth/signup.html", {"error": None})


@router.get("/dashboard", response_model=None)
async def dashboard_page(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    user = await get_current_user(request, session)
    if user is None:
        return RedirectResponse("/login", status_code=302)

    # Fetch user's API keys
    stmt = select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc())
    result = await session.execute(stmt)
    api_keys = list(result.scalars().all())

    return templates.TemplateResponse(
        request, "auth/dashboard.html", {"user": user, "api_keys": api_keys, "new_key": None}
    )


# --- Actions ---


@router.post("/auth/signup", response_model=None)
async def signup_action(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    email: str = Form(...),
    password: str = Form(...),
    name: str = Form(...),
) -> RedirectResponse | HTMLResponse:
    if len(password) < 8:
        return templates.TemplateResponse(
            request, "auth/signup.html", {"error": "A senha deve ter pelo menos 8 caracteres."}
        )

    existing = await get_user_by_email(session, email)
    if existing is not None:
        return templates.TemplateResponse(
            request, "auth/signup.html", {"error": "Este email ja esta cadastrado."}
        )

    user = await create_user(session, email, password, name)
    await session.commit()

    response = RedirectResponse("/dashboard", status_code=302)
    return _set_session_cookie(response, user)


@router.post("/auth/login", response_model=None)
async def login_action(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    email: str = Form(...),
    password: str = Form(...),
) -> RedirectResponse | HTMLResponse:
    user = await get_user_by_email(session, email)
    if user is None or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request, "auth/login.html", {"error": "Email ou senha incorretos."}
        )

    response = RedirectResponse("/dashboard", status_code=302)
    return _set_session_cookie(response, user)


@router.post("/auth/logout")
async def logout_action() -> RedirectResponse:
    response = RedirectResponse("/", status_code=302)
    response.delete_cookie(SESSION_COOKIE)
    return response


@router.post("/dashboard/keys/create", response_model=None)
async def create_api_key_action(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    key_name: str = Form(...),
) -> HTMLResponse:
    user = await get_current_user(request, session)
    if user is None:
        return RedirectResponse("/login", status_code=302)

    # Generate raw key
    raw_key = f"buscadou_{secrets.token_urlsafe(32)}"
    key_hash = hash_api_key(raw_key)

    api_key = ApiKey(
        id=uuid.uuid4(),
        user_id=user.id,
        key_hash=key_hash,
        name=key_name.strip(),
    )
    session.add(api_key)
    await session.commit()

    # Fetch all keys for display
    stmt = select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc())
    result = await session.execute(stmt)
    api_keys = list(result.scalars().all())

    return templates.TemplateResponse(
        request, "auth/dashboard.html", {"user": user, "api_keys": api_keys, "new_key": raw_key}
    )


@router.post("/dashboard/keys/{key_id}/revoke")
async def revoke_api_key_action(
    key_id: uuid.UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RedirectResponse:
    user = await get_current_user(request, session)
    if user is None:
        return RedirectResponse("/login", status_code=302)

    stmt = select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id)
    result = await session.execute(stmt)
    api_key = result.scalar_one_or_none()
    if api_key is not None:
        api_key.is_active = False
        await session.commit()

    return RedirectResponse("/dashboard", status_code=302)
