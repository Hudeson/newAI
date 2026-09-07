from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.acl import grant_default_acl
from shared.db.models import (
    AuditEvent,
    Chunk,
    ConnectorInstance,
    ConnectorSyncRun,
    Document,
    DocumentVersion,
    UploadJob,
    Workspace,
)
from shared.errors import AppError, ErrorCode
from shared.ingest import chunk_text, embed_text, tokenize
from shared.storage import get_storage

SUPPORTED_TYPES = {"s3"}


def create_connector(
    db: Session,
    *,
    tenant_id: str,
    workspace_id: str,
    user_id: str,
    type: str,
    name: str,
    config: dict,
) -> ConnectorInstance:
    if type not in SUPPORTED_TYPES:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            f"unsupported connector type: {type}",
            status_code=400,
            details={"supported": sorted(SUPPORTED_TYPES)},
        )
    ws = db.scalar(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.tenant_id == tenant_id,
            Workspace.status == "active",
        )
    )
    if ws is None:
        raise AppError(ErrorCode.NOT_FOUND, "workspace not found", status_code=404)

    row = ConnectorInstance(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        type=type,
        name=name,
        status="idle",
        config_json=json.dumps(config or {}),
        created_by=user_id,
    )
    db.add(row)
    db.flush()
    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_id=user_id,
            action="connector.created",
            resource_type="connector",
            resource_id=row.id,
            detail=json.dumps({"type": type, "name": name}),
        )
    )
    return row


def list_connectors(
    db: Session,
    *,
    tenant_id: str,
    workspace_id: str | None = None,
) -> list[ConnectorInstance]:
    stmt = select(ConnectorInstance).where(ConnectorInstance.tenant_id == tenant_id)
    if workspace_id:
        stmt = stmt.where(ConnectorInstance.workspace_id == workspace_id)
    return list(db.scalars(stmt.order_by(ConnectorInstance.created_at.desc())).all())


def _import_stub_object(
    db: Session,
    *,
    connector: ConnectorInstance,
    user_id: str,
    object_key: str,
    body: str,
) -> str:
    doc = Document(
        tenant_id=connector.tenant_id,
        workspace_id=connector.workspace_id,
        title=object_key.rsplit("/", 1)[-1],
        status="indexed",
        created_by=user_id,
    )
    db.add(doc)
    db.flush()
    storage = get_storage()
    stored_key = f"{connector.tenant_id}/{connector.workspace_id}/{doc.id}/v1/{object_key}"
    storage.put_bytes(stored_key, body.encode("utf-8"))
    version = DocumentVersion(
        tenant_id=connector.tenant_id,
        document_id=doc.id,
        version_no=1,
        object_key=stored_key,
        content_type="text/plain",
        size_bytes=len(body.encode("utf-8")),
        status="indexed",
    )
    db.add(version)
    db.flush()
    job = UploadJob(
        tenant_id=connector.tenant_id,
        workspace_id=connector.workspace_id,
        document_id=doc.id,
        version_id=version.id,
        filename=doc.title,
        content_type="text/plain",
        size_bytes=version.size_bytes,
        object_key=stored_key,
        status="indexed",
        created_by=user_id,
    )
    db.add(job)
    grant_default_acl(
        db,
        tenant_id=connector.tenant_id,
        document_id=doc.id,
        user_id=user_id,
        workspace_id=connector.workspace_id,
    )
    chunks = chunk_text(body)
    for i, content in enumerate(chunks):
        tokens = tokenize(content)
        db.add(
            Chunk(
                tenant_id=connector.tenant_id,
                workspace_id=connector.workspace_id,
                document_id=doc.id,
                version_id=version.id,
                ordinal=i,
                content=content,
                token_count=len(tokens),
                embedding_json=json.dumps(embed_text(content)),
                status="active",
            )
        )
    return doc.id


def sync_connector(
    db: Session,
    *,
    tenant_id: str,
    connector_id: str,
    user_id: str,
) -> ConnectorSyncRun:
    connector = db.scalar(
        select(ConnectorInstance).where(
            ConnectorInstance.id == connector_id,
            ConnectorInstance.tenant_id == tenant_id,
        )
    )
    if connector is None:
        raise AppError(ErrorCode.NOT_FOUND, "connector not found", status_code=404)

    config = json.loads(connector.config_json or "{}")
    bucket = config.get("bucket") or "kb-documents"
    prefix = config.get("prefix") or "inbox/"
    sample_key = f"{prefix.rstrip('/')}/sample-from-{connector.type}.txt"
    body = (
        f"# Connector import\n\n"
        f"Stub sync from s3://{bucket}/{sample_key}\n\n"
        f"This document was imported by connector {connector.name}.\n"
    )

    connector.status = "syncing"
    db.flush()
    run = ConnectorSyncRun(
        tenant_id=tenant_id,
        connector_id=connector.id,
        status="running",
    )
    db.add(run)
    db.flush()

    try:
        doc_id = _import_stub_object(
            db,
            connector=connector,
            user_id=user_id,
            object_key=sample_key,
            body=body,
        )
        run.items_seen = 1
        run.items_imported = 1
        run.status = "completed"
        run.detail_json = json.dumps(
            {"document_id": doc_id, "object_key": sample_key, "bucket": bucket}
        )
        connector.status = "idle"
        connector.updated_at = datetime.now(UTC)
        db.add(
            AuditEvent(
                tenant_id=tenant_id,
                actor_id=user_id,
                action="connector.sync.completed",
                resource_type="connector",
                resource_id=connector.id,
                detail=run.detail_json,
            )
        )
    except Exception as exc:  # noqa: BLE001 - surface as sync failure
        run.status = "failed"
        run.error_message = str(exc)
        connector.status = "error"
        raise
    finally:
        db.flush()
    return run
