from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, Header
from shared.config import get_settings
from shared.db import get_db
from shared.db.models import User
from shared.errors import AppError, ErrorCode
from sqlalchemy import select
from sqlalchemy.orm import Session


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return f"{salt}:{digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        salt, stored = password_hash.split(":", 1)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return hmac.compare_digest(digest.hex(), stored)


def create_access_token(*, user_id: str, tenant_id: str, role: str, email: str) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_expire_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    tenant_id: str
    role: str
    email: str


def decode_token(token: str) -> AuthContext:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise AppError(ErrorCode.UNAUTHENTICATED, "invalid token", status_code=401) from exc
    return AuthContext(
        user_id=str(payload["sub"]),
        tenant_id=str(payload["tenant_id"]),
        role=str(payload.get("role", "member")),
        email=str(payload.get("email", "")),
    )


def get_current_auth(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthContext:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError(ErrorCode.UNAUTHENTICATED, "missing bearer token", status_code=401)
    token = authorization.split(" ", 1)[1].strip()
    ctx = decode_token(token)
    user = db.scalar(select(User).where(User.id == ctx.user_id, User.tenant_id == ctx.tenant_id))
    if user is None or user.status != "active":
        raise AppError(ErrorCode.UNAUTHENTICATED, "user inactive or missing", status_code=401)
    return AuthContext(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        email=user.email,
    )


def require_admin(auth: AuthContext = Depends(get_current_auth)) -> AuthContext:
    if auth.role not in {"admin", "owner"}:
        raise AppError(ErrorCode.FORBIDDEN, "admin role required", status_code=403)
    return auth
