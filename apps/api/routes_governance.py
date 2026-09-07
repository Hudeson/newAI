from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from shared.audit_export import create_audit_export, get_audit_export, read_export_bytes
from shared.db import get_db
from shared.db.models import AuditEvent, TenantQuota, UploadJob
from shared.errors import AppError, ErrorCode
from shared.policy import list_policies, upsert_policy
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


class ModelPolicyOut(BaseModel):
    sensitivity: str
    provider: str
    model: str


class ModelPolicyUpdate(BaseModel):
    sensitivity: str = Field(pattern=r"^L[1-4]$")
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=64)


class AuditExportOut(BaseModel):
    id: str
    status: str
    event_count: int
    object_key: str
    download_url: str


@router.get("/admin/models/policy", response_model=list[ModelPolicyOut])
def get_model_policy(
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[ModelPolicyOut]:
    rows = list_policies(db, tenant_id=auth.tenant_id)
    return [
        ModelPolicyOut(sensitivity=r.sensitivity, provider=r.provider, model=r.model) for r in rows
    ]


@router.put("/admin/models/policy", response_model=list[ModelPolicyOut])
def put_model_policy(
    body: list[ModelPolicyUpdate],
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[ModelPolicyOut]:
    updated = []
    for item in body:
        updated.append(
            upsert_policy(
                db,
                tenant_id=auth.tenant_id,
                sensitivity=item.sensitivity,
                provider=item.provider,
                model=item.model,
            )
        )
    db.add(
        AuditEvent(
            tenant_id=auth.tenant_id,
            actor_id=auth.user_id,
            action="admin.models.policy.updated",
            resource_type="model_route_policy",
            resource_id=auth.tenant_id,
            detail=json.dumps([b.model_dump() for b in body]),
        )
    )
    return [
        ModelPolicyOut(sensitivity=r.sensitivity, provider=r.provider, model=r.model)
        for r in updated
    ]


@router.post("/admin/audit-exports", response_model=AuditExportOut)
def post_audit_export(
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AuditExportOut:
    export = create_audit_export(db, tenant_id=auth.tenant_id, user_id=auth.user_id)
    return AuditExportOut(
        id=export.id,
        status=export.status,
        event_count=export.event_count,
        object_key=export.object_key,
        download_url=f"/v1/admin/audit-exports/{export.id}/download",
    )


@router.get("/admin/audit-exports/{export_id}/download")
def download_audit_export(
    export_id: str,
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    export = get_audit_export(db, tenant_id=auth.tenant_id, export_id=export_id)
    if export is None:
        raise AppError(ErrorCode.NOT_FOUND, "audit export not found", status_code=404)
    data = read_export_bytes(export)
    return Response(
        content=data,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="audit-{export.id}.json"'},
    )
