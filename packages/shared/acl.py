from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.db.models import DocumentAcl, Workspace


def list_workspace_ids(db: Session, *, tenant_id: str) -> list[str]:
    rows = db.scalars(
        select(Workspace.id).where(Workspace.tenant_id == tenant_id, Workspace.status == "active")
    ).all()
    return list(rows)


def grant_default_acl(
    db: Session,
    *,
    tenant_id: str,
    document_id: str,
    user_id: str,
    workspace_id: str,
) -> None:
    """Owner + workspace read grants (idempotent)."""
    existing = db.scalars(select(DocumentAcl).where(DocumentAcl.document_id == document_id)).all()
    keys = {(a.principal_type, a.principal_id, a.permission) for a in existing}
    wanted = [
        ("user", user_id, "read"),
        ("user", user_id, "write"),
        ("workspace", workspace_id, "read"),
    ]
    for ptype, pid, perm in wanted:
        if (ptype, pid, perm) in keys:
            continue
        db.add(
            DocumentAcl(
                tenant_id=tenant_id,
                document_id=document_id,
                principal_type=ptype,
                principal_id=pid,
                permission=perm,
            )
        )


def readable_document_ids(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    workspace_ids: list[str] | None = None,
) -> set[str]:
    if workspace_ids is None:
        workspace_ids = list_workspace_ids(db, tenant_id=tenant_id)
    rows = db.scalars(
        select(DocumentAcl).where(
            DocumentAcl.tenant_id == tenant_id,
            DocumentAcl.permission == "read",
        )
    ).all()
    allowed: set[str] = set()
    ws = set(workspace_ids)
    for acl in rows:
        if acl.principal_type == "user" and acl.principal_id == user_id:
            allowed.add(acl.document_id)
        elif acl.principal_type == "workspace" and acl.principal_id in ws:
            allowed.add(acl.document_id)
    return allowed


def can_read_document(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    document_id: str,
    workspace_ids: list[str] | None = None,
) -> bool:
    return document_id in readable_document_ids(
        db, tenant_id=tenant_id, user_id=user_id, workspace_ids=workspace_ids
    )


def replace_document_acl(
    db: Session,
    *,
    tenant_id: str,
    document_id: str,
    entries: list[tuple[str, str, str]],
) -> None:
    old = db.scalars(select(DocumentAcl).where(DocumentAcl.document_id == document_id)).all()
    for row in old:
        db.delete(row)
    db.flush()
    for ptype, pid, perm in entries:
        db.add(
            DocumentAcl(
                tenant_id=tenant_id,
                document_id=document_id,
                principal_type=ptype,
                principal_id=pid,
                permission=perm,
            )
        )
