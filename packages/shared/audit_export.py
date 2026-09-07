from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.db.models import AuditEvent, AuditExport
from shared.storage import get_storage


def create_audit_export(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    limit: int = 5000,
) -> AuditExport:
    rows = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == tenant_id)
        .order_by(AuditEvent.created_at.desc())
        .limit(limit)
    ).all()
    payload = {
        "tenant_id": tenant_id,
        "exported_at": datetime.now(UTC).isoformat(),
        "event_count": len(rows),
        "events": [
            {
                "id": r.id,
                "actor_id": r.actor_id,
                "action": r.action,
                "resource_type": r.resource_type,
                "resource_id": r.resource_id,
                "request_id": r.request_id,
                "detail": r.detail,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }
    export = AuditExport(
        tenant_id=tenant_id,
        created_by=user_id,
        status="ready",
        event_count=len(rows),
        detail_json=json.dumps({"limit": limit}),
    )
    db.add(export)
    db.flush()
    object_key = f"{tenant_id}/exports/audit/{export.id}.json"
    get_storage().put_bytes(
        object_key,
        json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
    )
    export.object_key = object_key
    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_id=user_id,
            action="admin.audit.exported",
            resource_type="audit_export",
            resource_id=export.id,
            detail=json.dumps({"event_count": len(rows)}),
        )
    )
    db.flush()
    return export


def get_audit_export(db: Session, *, tenant_id: str, export_id: str) -> AuditExport | None:
    return db.scalar(
        select(AuditExport).where(
            AuditExport.id == export_id,
            AuditExport.tenant_id == tenant_id,
        )
    )


def read_export_bytes(export: AuditExport) -> bytes:
    return get_storage().get_bytes(export.object_key)
