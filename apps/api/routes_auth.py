from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import (
    AuthContext,
    create_access_token,
    get_current_auth,
    hash_password,
    require_admin,
    verify_password,
)
from shared.db import get_db
from shared.db.models import AuditEvent, Tenant, User, Workspace
from shared.errors import AppError, ErrorCode

router = APIRouter(prefix="/v1", tags=["auth"])


class RegisterRequest(BaseModel):
    tenant_name: str = Field(min_length=2, max_length=200)
    tenant_slug: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9-]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=200)


class LoginRequest(BaseModel):
    tenant_slug: str
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tenant_id: str
    user_id: str


class MeResponse(BaseModel):
    user_id: str
    tenant_id: str
    email: str
    display_name: str
    role: str


class UserOut(BaseModel):
    user_id: str
    email: str
    display_name: str
    role: str
    status: str


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    publish_mode: str = "auto"


class WorkspaceOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    slug: str
    publish_mode: str
    status: str


@router.post("/auth/register", response_model=TokenResponse)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    exists = db.scalar(select(Tenant).where(Tenant.slug == body.tenant_slug))
    if exists:
        raise AppError(ErrorCode.CONFLICT, "tenant slug already exists", status_code=409)

    tenant = Tenant(name=body.tenant_name, slug=body.tenant_slug)
    db.add(tenant)
    db.flush()

    user = User(
        tenant_id=tenant.id,
        email=str(body.email).lower(),
        display_name=body.display_name or str(body.email).split("@")[0],
        password_hash=hash_password(body.password),
        role="admin",
    )
    workspace = Workspace(
        tenant_id=tenant.id,
        name="Default",
        slug="default",
        publish_mode="auto",
    )
    db.add_all([user, workspace])
    db.flush()
    db.add(
        AuditEvent(
            tenant_id=tenant.id,
            actor_id=user.id,
            action="auth.register",
            resource_type="tenant",
            resource_id=tenant.id,
        )
    )

    token = create_access_token(
        user_id=user.id, tenant_id=tenant.id, role=user.role, email=user.email
    )
    return TokenResponse(access_token=token, tenant_id=tenant.id, user_id=user.id)


@router.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    tenant = db.scalar(select(Tenant).where(Tenant.slug == body.tenant_slug))
    if tenant is None:
        raise AppError(ErrorCode.UNAUTHENTICATED, "invalid credentials", status_code=401)

    user = db.scalar(
        select(User).where(User.tenant_id == tenant.id, User.email == str(body.email).lower())
    )
    if user is None or not verify_password(body.password, user.password_hash):
        raise AppError(ErrorCode.UNAUTHENTICATED, "invalid credentials", status_code=401)
    if user.status != "active":
        raise AppError(ErrorCode.FORBIDDEN, "user disabled", status_code=403)

    token = create_access_token(
        user_id=user.id, tenant_id=user.tenant_id, role=user.role, email=user.email
    )
    return TokenResponse(access_token=token, tenant_id=user.tenant_id, user_id=user.id)


@router.get("/me", response_model=MeResponse)
def me(auth: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)) -> MeResponse:
    user = db.scalar(select(User).where(User.id == auth.user_id))
    assert user is not None
    return MeResponse(
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
    )


@router.get("/users", response_model=list[UserOut])
def list_users(
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> list[UserOut]:
    rows = db.scalars(
        select(User).where(User.tenant_id == auth.tenant_id).order_by(User.created_at.asc())
    ).all()
    return [
        UserOut(
            user_id=u.id,
            email=u.email,
            display_name=u.display_name,
            role=u.role,
            status=u.status,
        )
        for u in rows
    ]


@router.get("/workspaces", response_model=list[WorkspaceOut])
def list_workspaces(
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> list[WorkspaceOut]:
    rows = db.scalars(
        select(Workspace).where(Workspace.tenant_id == auth.tenant_id, Workspace.status == "active")
    ).all()
    return [
        WorkspaceOut(
            id=w.id,
            tenant_id=w.tenant_id,
            name=w.name,
            slug=w.slug,
            publish_mode=w.publish_mode,
            status=w.status,
        )
        for w in rows
    ]


class InviteUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=200)
    role: str = Field(default="member", pattern=r"^(member|viewer|admin)$")


class InviteUserResponse(BaseModel):
    user_id: str
    tenant_id: str
    email: str
    role: str
    access_token: str
    token_type: str = "bearer"


@router.post("/users/invite", response_model=InviteUserResponse)
def invite_user(
    body: InviteUserRequest,
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> InviteUserResponse:
    email = str(body.email).lower()
    exists = db.scalar(select(User).where(User.tenant_id == auth.tenant_id, User.email == email))
    if exists:
        raise AppError(ErrorCode.CONFLICT, "user already exists", status_code=409)

    user = User(
        tenant_id=auth.tenant_id,
        email=email,
        display_name=body.display_name or email.split("@")[0],
        password_hash=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    db.flush()
    db.add(
        AuditEvent(
            tenant_id=auth.tenant_id,
            actor_id=auth.user_id,
            action="auth.invite",
            resource_type="user",
            resource_id=user.id,
        )
    )
    token = create_access_token(
        user_id=user.id, tenant_id=user.tenant_id, role=user.role, email=user.email
    )
    return InviteUserResponse(
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        role=user.role,
        access_token=token,
    )


@router.post("/workspaces", response_model=WorkspaceOut)
def create_workspace(
    body: WorkspaceCreate,
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> WorkspaceOut:
    exists = db.scalar(
        select(Workspace).where(Workspace.tenant_id == auth.tenant_id, Workspace.slug == body.slug)
    )
    if exists:
        raise AppError(ErrorCode.CONFLICT, "workspace slug exists", status_code=409)

    ws = Workspace(
        tenant_id=auth.tenant_id,
        name=body.name,
        slug=body.slug,
        publish_mode=body.publish_mode,
    )
    db.add(ws)
    db.flush()
    return WorkspaceOut(
        id=ws.id,
        tenant_id=ws.tenant_id,
        name=ws.name,
        slug=ws.slug,
        publish_mode=ws.publish_mode,
        status=ws.status,
    )
