from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from shared.db import get_db
from shared.db.models import Group, GroupMember, User
from shared.errors import AppError, ErrorCode
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import AuthContext, decode_token, hash_password, require_admin

router = APIRouter(prefix="/scim/v2", tags=["scim"])


class ScimName(BaseModel):
    formatted: str | None = None


class ScimEmail(BaseModel):
    value: str
    primary: bool = True


class ScimUserCreate(BaseModel):
    userName: str = Field(min_length=3, max_length=320)
    displayName: str | None = None
    name: ScimName | None = None
    emails: list[ScimEmail] = Field(default_factory=list)
    active: bool = True
    externalId: str | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


class ScimGroupMember(BaseModel):
    value: str


class ScimGroupCreate(BaseModel):
    displayName: str = Field(min_length=1, max_length=200)
    externalId: str | None = None
    members: list[ScimGroupMember] = Field(default_factory=list)


def _scim_auth(request: Request, db: Session) -> AuthContext:
    authorization = request.headers.get("Authorization")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError(ErrorCode.UNAUTHENTICATED, "missing bearer token", status_code=401)
    token = authorization.split(" ", 1)[1].strip()
    ctx = decode_token(token)
    user = db.scalar(select(User).where(User.id == ctx.user_id, User.tenant_id == ctx.tenant_id))
    if user is None or user.status != "active":
        raise AppError(ErrorCode.UNAUTHENTICATED, "user inactive or missing", status_code=401)
    auth = AuthContext(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        email=user.email,
    )
    return require_admin(auth)


def _user_resource(user: User) -> dict:
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "id": user.id,
        "userName": user.email,
        "displayName": user.display_name or user.email,
        "active": user.status == "active",
        "emails": [{"value": user.email, "primary": True}],
        "meta": {"resourceType": "User"},
    }


def _group_resource(group: Group, members: list[GroupMember]) -> dict:
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
        "id": group.id,
        "displayName": group.name,
        "externalId": group.external_id or None,
        "members": [{"value": m.user_id} for m in members],
        "meta": {"resourceType": "Group"},
    }


@router.get("/Users")
def list_users(
    request: Request,
    db: Session = Depends(get_db),
    startIndex: int = Query(default=1, ge=1),
    count: int = Query(default=100, ge=1, le=200),
) -> dict:
    auth = _scim_auth(request, db)
    rows = db.scalars(
        select(User)
        .where(User.tenant_id == auth.tenant_id)
        .order_by(User.created_at.asc())
        .offset(startIndex - 1)
        .limit(count)
    ).all()
    total = len(
        db.scalars(select(User).where(User.tenant_id == auth.tenant_id)).all()
    )
    return {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": total,
        "startIndex": startIndex,
        "itemsPerPage": len(rows),
        "Resources": [_user_resource(u) for u in rows],
    }


@router.post("/Users", status_code=201)
def create_user(body: ScimUserCreate, request: Request, db: Session = Depends(get_db)) -> dict:
    auth = _scim_auth(request, db)
    email = (body.emails[0].value if body.emails else body.userName).lower()
    existing = db.scalar(select(User).where(User.tenant_id == auth.tenant_id, User.email == email))
    if existing:
        raise AppError(ErrorCode.CONFLICT, "user already exists", status_code=409)
    password = body.password or "ChangeMe123!"
    user = User(
        tenant_id=auth.tenant_id,
        email=email,
        display_name=body.displayName or (body.name.formatted if body.name else "") or email,
        password_hash=hash_password(password),
        role="member",
        status="active" if body.active else "disabled",
    )
    db.add(user)
    db.flush()
    return _user_resource(user)


@router.get("/Groups")
def list_groups(
    request: Request,
    db: Session = Depends(get_db),
    startIndex: int = Query(default=1, ge=1),
    count: int = Query(default=100, ge=1, le=200),
) -> dict:
    auth = _scim_auth(request, db)
    rows = db.scalars(
        select(Group)
        .where(Group.tenant_id == auth.tenant_id)
        .order_by(Group.created_at.asc())
        .offset(startIndex - 1)
        .limit(count)
    ).all()
    resources = []
    for g in rows:
        members = list(
            db.scalars(select(GroupMember).where(GroupMember.group_id == g.id)).all()
        )
        resources.append(_group_resource(g, members))
    total = len(db.scalars(select(Group).where(Group.tenant_id == auth.tenant_id)).all())
    return {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": total,
        "startIndex": startIndex,
        "itemsPerPage": len(resources),
        "Resources": resources,
    }


@router.post("/Groups", status_code=201)
def create_group(body: ScimGroupCreate, request: Request, db: Session = Depends(get_db)) -> dict:
    auth = _scim_auth(request, db)
    external_id = body.externalId or body.displayName
    existing = db.scalar(
        select(Group).where(Group.tenant_id == auth.tenant_id, Group.external_id == external_id)
    )
    if existing:
        raise AppError(ErrorCode.CONFLICT, "group already exists", status_code=409)
    group = Group(
        tenant_id=auth.tenant_id,
        name=body.displayName,
        external_id=external_id,
        source="scim",
        status="active",
    )
    db.add(group)
    db.flush()
    members: list[GroupMember] = []
    for m in body.members:
        user = db.scalar(
            select(User).where(User.id == m.value, User.tenant_id == auth.tenant_id)
        )
        if user is None:
            continue
        gm = GroupMember(tenant_id=auth.tenant_id, group_id=group.id, user_id=user.id)
        db.add(gm)
        members.append(gm)
    db.flush()
    return _group_resource(group, members)
