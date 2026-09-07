from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from shared.db import get_db
from shared.db.models import AuditEvent, TenantQuota, UploadJob
from shared.quota import list_quotas, set_quota, usage_summary
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import AuthContext, get_current_auth, require_admin

router = APIRouter(prefix="/v1", tags=["governance"])


class QuotaOut(BaseModel):
    meter: str
    limit: int
    window: str


class QuotaUpdate(BaseModel):
    meter: str = Field(min_length=1, max_length=64)
    limit: int = Field(ge=0)
    window: str | None = Field(default=None, pattern=r"^(day|lifetime)$")


class UsageMeterOut(BaseModel):
    meter: str
    limit: int
    used: int
    remaining: int
    window: str


class AuditOut(BaseModel):
    id: str
    action: str
    resource_type: str
    resource_id: str
    actor_id: str | None
    detail: str


class JobOut(BaseModel):
    id: str
    filename: str
    status: str
    workspace_id: str
    document_id: str
    error_message: str


@router.get("/admin/quotas", response_model=list[QuotaOut])
def get_quotas(
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[QuotaOut]:
    rows = list_quotas(db, tenant_id=auth.tenant_id)
    return [QuotaOut(meter=r.meter, limit=r.limit_value, window=r.window) for r in rows]


@router.put("/admin/quotas", response_model=list[QuotaOut])
def put_quotas(
    body: list[QuotaUpdate],
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[QuotaOut]:
    updated: list[TenantQuota] = []
    for item in body:
        updated.append(
            set_quota(
                db,
                tenant_id=auth.tenant_id,
                meter=item.meter,
                limit_value=item.limit,
                window=item.window,
            )
        )
    db.add(
        AuditEvent(
            tenant_id=auth.tenant_id,
            actor_id=auth.user_id,
            action="admin.quotas.updated",
            resource_type="tenant_quota",
            resource_id=auth.tenant_id,
            detail=json.dumps([b.model_dump() for b in body]),
        )
    )
    return [QuotaOut(meter=r.meter, limit=r.limit_value, window=r.window) for r in updated]


@router.get("/admin/usage", response_model=list[UsageMeterOut])
def admin_usage(
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[UsageMeterOut]:
    return [UsageMeterOut(**row) for row in usage_summary(db, tenant_id=auth.tenant_id)]


@router.get("/usage/summary", response_model=list[UsageMeterOut])
def member_usage_summary(
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> list[UsageMeterOut]:
    return [UsageMeterOut(**row) for row in usage_summary(db, tenant_id=auth.tenant_id)]


@router.get("/admin/audit-events", response_model=list[AuditOut])
def list_audit(
    limit: int = Query(default=50, ge=1, le=200),
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[AuditOut]:
    rows = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == auth.tenant_id)
        .order_by(AuditEvent.created_at.desc())
        .limit(limit)
    ).all()
    return [
        AuditOut(
            id=r.id,
            action=r.action,
            resource_type=r.resource_type,
            resource_id=r.resource_id,
            actor_id=r.actor_id,
            detail=r.detail,
        )
        for r in rows
    ]


@router.get("/admin/jobs", response_model=list[JobOut])
def list_failed_jobs(
    status: str = Query(default="failed"),
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[JobOut]:
    rows = db.scalars(
        select(UploadJob)
        .where(UploadJob.tenant_id == auth.tenant_id, UploadJob.status == status)
        .order_by(UploadJob.created_at.desc())
        .limit(50)
    ).all()
    return [
        JobOut(
            id=r.id,
            filename=r.filename,
            status=r.status,
            workspace_id=r.workspace_id,
            document_id=r.document_id,
            error_message=r.error_message,
        )
        for r in rows
    ]
