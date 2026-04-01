"""Authentication service - password hashing and session management."""

from __future__ import annotations

import uuid

import bcrypt as _bcrypt
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.config import settings
from src.models.user import User

_serializer = URLSafeTimedSerializer(settings.api_secret_key)
SESSION_COOKIE = "buscadou_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return _bcrypt.checkpw(password.encode(), password_hash.encode())


def create_session_token(user_id: uuid.UUID) -> str:
    return _serializer.dumps(str(user_id))


def decode_session_token(token: str) -> uuid.UUID | None:
    try:
        user_id_str = _serializer.loads(token, max_age=SESSION_MAX_AGE)
        return uuid.UUID(user_id_str)
    except (BadSignature, ValueError):
        return None


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    stmt = select(User).where(User.email == email)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    stmt = select(User).where(User.id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create_user(session: AsyncSession, email: str, password: str, name: str) -> User:
    user = User(
        id=uuid.uuid4(),
        email=email.lower().strip(),
        password_hash=hash_password(password),
        name=name.strip(),
    )
    session.add(user)
    await session.flush()
    return user
