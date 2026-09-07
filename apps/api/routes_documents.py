from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from shared.acl import can_read_document, replace_document_acl
from shared.db import get_db
from shared.db.models import Chunk, Document, DocumentAcl
from shared.errors import AppError, ErrorCode
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import AuthContext, get_current_auth, require_admin

router = APIRouter(prefix="/v1", tags=["documents"])


class DocumentOut(BaseModel):
    id: str
    tenant_id: str
    workspace_id: str
    title: str
    status: str
    sensitivity: str = "L2"
    created_by: str
    chunk_count: int = 0


class AclEntry(BaseModel):
    principal_type: str = Field(pattern=r"^(user|workspace|group)$")
    principal_id: str
    permission: str = Field(default="read", pattern=r"^(read|write)$")


class AclReplaceRequest(BaseModel):
    entries: list[AclEntry] = Field(min_length=1)


class AclOut(BaseModel):
    document_id: str
    entries: list[AclEntry]


class SensitivityUpdate(BaseModel):
    sensitivity: str = Field(pattern=r"^L[1-4]$")


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(
    workspace_id: str | None = None,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> list[DocumentOut]:
    q = select(Document).where(Document.tenant_id == auth.tenant_id)
    if workspace_id:
        q = q.where(Document.workspace_id == workspace_id)
    rows = db.scalars(q.order_by(Document.created_at.desc())).all()
    out: list[DocumentOut] = []
    for doc in rows:
        if not can_read_document(
            db, tenant_id=auth.tenant_id, user_id=auth.user_id, document_id=doc.id
        ):
            continue
        chunk_count = len(
            db.scalars(
                select(Chunk.id).where(
                    Chunk.tenant_id == auth.tenant_id,
                    Chunk.document_id == doc.id,
                    Chunk.status == "active",
                )
            ).all()
        )
        out.append(
            DocumentOut(
                id=doc.id,
                tenant_id=doc.tenant_id,
                workspace_id=doc.workspace_id,
                title=doc.title,
                status=doc.status,
                sensitivity=doc.sensitivity,
                created_by=doc.created_by,
                chunk_count=chunk_count,
            )
        )
    return out


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: str,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> DocumentOut:
    doc = db.scalar(
        select(Document).where(Document.id == document_id, Document.tenant_id == auth.tenant_id)
    )
    if doc is None or not can_read_document(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, document_id=document_id
    ):
        raise AppError(ErrorCode.NOT_FOUND, "document not found", status_code=404)

    chunk_count = len(
        db.scalars(
            select(Chunk.id).where(
                Chunk.tenant_id == auth.tenant_id,
                Chunk.document_id == document_id,
                Chunk.status == "active",
            )
        ).all()
    )
    return DocumentOut(
        id=doc.id,
        tenant_id=doc.tenant_id,
        workspace_id=doc.workspace_id,
        title=doc.title,
        status=doc.status,
        sensitivity=doc.sensitivity,
        created_by=doc.created_by,
        chunk_count=chunk_count,
    )


@router.patch("/documents/{document_id}/sensitivity", response_model=DocumentOut)
def patch_sensitivity(
    document_id: str,
    body: SensitivityUpdate,
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> DocumentOut:
    doc = db.scalar(
        select(Document).where(Document.id == document_id, Document.tenant_id == auth.tenant_id)
    )
    if doc is None:
        raise AppError(ErrorCode.NOT_FOUND, "document not found", status_code=404)
    doc.sensitivity = body.sensitivity
    db.flush()
    chunk_count = len(
        db.scalars(
            select(Chunk.id).where(
                Chunk.tenant_id == auth.tenant_id,
                Chunk.document_id == document_id,
                Chunk.status == "active",
            )
        ).all()
    )
    return DocumentOut(
        id=doc.id,
        tenant_id=doc.tenant_id,
        workspace_id=doc.workspace_id,
        title=doc.title,
        status=doc.status,
        sensitivity=doc.sensitivity,
        created_by=doc.created_by,
        chunk_count=chunk_count,
    )


@router.get("/documents/{document_id}/acl", response_model=AclOut)
def get_document_acl(
    document_id: str,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> AclOut:
    doc = db.scalar(
        select(Document).where(Document.id == document_id, Document.tenant_id == auth.tenant_id)
    )
    if doc is None or not can_read_document(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, document_id=document_id
    ):
        raise AppError(ErrorCode.NOT_FOUND, "document not found", status_code=404)
    rows = db.scalars(select(DocumentAcl).where(DocumentAcl.document_id == document_id)).all()
    return AclOut(
        document_id=document_id,
        entries=[
            AclEntry(
                principal_type=r.principal_type,
                principal_id=r.principal_id,
                permission=r.permission,
            )
            for r in rows
        ],
    )


@router.put("/documents/{document_id}/acl", response_model=AclOut)
def put_document_acl(
    document_id: str,
    body: AclReplaceRequest,
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AclOut:
    doc = db.scalar(
        select(Document).where(Document.id == document_id, Document.tenant_id == auth.tenant_id)
    )
    if doc is None:
        raise AppError(ErrorCode.NOT_FOUND, "document not found", status_code=404)
    replace_document_acl(
        db,
        tenant_id=auth.tenant_id,
        document_id=document_id,
        entries=[(e.principal_type, e.principal_id, e.permission) for e in body.entries],
    )
    db.flush()
    return AclOut(document_id=document_id, entries=body.entries)
