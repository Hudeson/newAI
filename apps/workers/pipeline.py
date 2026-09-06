from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.acl import grant_default_acl
from shared.db.models import AuditEvent, Chunk, Document, DocumentVersion, UploadJob
from shared.ingest import chunk_text, embed_text, tokenize
from shared.logging import get_logger
from shared.storage import get_storage

logger = get_logger("worker.pipeline")


@dataclass
class ProcessResult:
    job_id: str
    document_id: str
    chunk_count: int
    status: str


def process_upload_job(db: Session, job_id: str, *, actor_id: str | None = None) -> ProcessResult:
    job = db.scalar(select(UploadJob).where(UploadJob.id == job_id))
    if job is None:
        raise ValueError(f"job not found: {job_id}")
    if job.status not in {"queued", "processing", "indexed", "failed"}:
        raise ValueError(f"job status not processable: {job.status}")

    job.status = "processing"
    db.flush()

    try:
        storage = get_storage()
        raw = storage.get_bytes(job.object_key)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="ignore")

        old = db.scalars(select(Chunk).where(Chunk.version_id == job.version_id)).all()
        for c in old:
            db.delete(c)
        db.flush()

        pieces = chunk_text(text)
        for i, piece in enumerate(pieces):
            emb = embed_text(piece)
            db.add(
                Chunk(
                    tenant_id=job.tenant_id,
                    workspace_id=job.workspace_id,
                    document_id=job.document_id,
                    version_id=job.version_id,
                    ordinal=i,
                    content=piece,
                    token_count=len(tokenize(piece)),
                    embedding_json=json.dumps(emb),
                    status="active",
                )
            )

        grant_default_acl(
            db,
            tenant_id=job.tenant_id,
            document_id=job.document_id,
            user_id=job.created_by,
            workspace_id=job.workspace_id,
        )

        version = db.scalar(select(DocumentVersion).where(DocumentVersion.id == job.version_id))
        doc = db.scalar(select(Document).where(Document.id == job.document_id))
        if version:
            version.status = "indexed"
        if doc:
            doc.status = "indexed"
        job.status = "indexed"
        job.error_message = ""
        db.add(
            AuditEvent(
                tenant_id=job.tenant_id,
                actor_id=actor_id or job.created_by,
                action="document.indexed",
                resource_type="document",
                resource_id=job.document_id,
                detail=json.dumps({"job_id": job.id, "chunk_count": len(pieces)}),
            )
        )
        db.flush()
        logger.info("job_indexed", job_id=job.id, chunks=len(pieces))
        return ProcessResult(
            job_id=job.id,
            document_id=job.document_id,
            chunk_count=len(pieces),
            status="indexed",
        )
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error_message = str(exc)[:1000]
        doc = db.scalar(select(Document).where(Document.id == job.document_id))
        if doc:
            doc.status = "failed"
        db.flush()
        logger.exception("job_failed", job_id=job.id)
        raise


def claim_queued_jobs(db: Session, *, limit: int = 10) -> list[str]:
    rows = db.scalars(
        select(UploadJob).where(UploadJob.status == "queued").limit(limit)
    ).all()
    return [r.id for r in rows]
