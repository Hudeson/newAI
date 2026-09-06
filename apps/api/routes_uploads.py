from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import AuthContext, get_current_auth
from shared.config import get_settings
from shared.db import get_db
from shared.db.models import AuditEvent, Document, DocumentVersion, UploadJob, Workspace
from shared.errors import AppError, ErrorCode
from shared.storage import get_storage
from workers.pipeline import process_upload_job

router = APIRouter(prefix="/v1", tags=["uploads"])


class PresignRequest(BaseModel):
    workspace_id: str
    filename: str = Field(min_length=1, max_length=500)
    content_type: str = "text/plain"
    size_bytes: int = Field(default=0, ge=0)
    idempotency_key: str | None = Field(default=None, max_length=100)


class PresignResponse(BaseModel):
    upload_job_id: str
    document_id: str
    version_id: str
    object_key: str
    upload_url: str
    upload_method: str = "PUT"


class UploadJobOut(BaseModel):
    id: str
    tenant_id: str
    workspace_id: str
    document_id: str
    version_id: str
    filename: str
    status: str
    object_key: str
    size_bytes: int
    error_message: str = ""


def _workspace(db: Session, auth: AuthContext, workspace_id: str) -> Workspace:
    ws = db.scalar(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.tenant_id == auth.tenant_id,
            Workspace.status == "active",
        )
    )
    if ws is None:
        raise AppError(ErrorCode.NOT_FOUND, "workspace not found", status_code=404)
    return ws


def _job_out(job: UploadJob) -> UploadJobOut:
    return UploadJobOut(
        id=job.id,
        tenant_id=job.tenant_id,
        workspace_id=job.workspace_id,
        document_id=job.document_id,
        version_id=job.version_id,
        filename=job.filename,
        status=job.status,
        object_key=job.object_key,
        size_bytes=job.size_bytes,
        error_message=job.error_message,
    )


@router.post("/uploads/presign", response_model=PresignResponse)
def presign_upload(
    body: PresignRequest,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> PresignResponse:
    _workspace(db, auth, body.workspace_id)

    if body.idempotency_key:
        existing = db.scalar(
            select(UploadJob).where(
                UploadJob.tenant_id == auth.tenant_id,
                UploadJob.idempotency_key == body.idempotency_key,
            )
        )
        if existing is not None:
            return PresignResponse(
                upload_job_id=existing.id,
                document_id=existing.document_id,
                version_id=existing.version_id,
                object_key=existing.object_key,
                upload_url=f"/v1/upload-jobs/{existing.id}/content",
            )

    doc = Document(
        tenant_id=auth.tenant_id,
        workspace_id=body.workspace_id,
        title=body.filename,
        status="uploading",
        created_by=auth.user_id,
    )
    db.add(doc)
    db.flush()

    version = DocumentVersion(
        tenant_id=auth.tenant_id,
        document_id=doc.id,
        version_no=1,
        content_type=body.content_type,
        size_bytes=body.size_bytes,
        status="pending",
    )
    db.add(version)
    db.flush()

    object_key = f"{auth.tenant_id}/{body.workspace_id}/{doc.id}/v1/raw/{body.filename}"
    version.object_key = object_key

    job = UploadJob(
        tenant_id=auth.tenant_id,
        workspace_id=body.workspace_id,
        document_id=doc.id,
        version_id=version.id,
        filename=body.filename,
        content_type=body.content_type,
        size_bytes=body.size_bytes,
        object_key=object_key,
        status="created",
        idempotency_key=body.idempotency_key,
        created_by=auth.user_id,
    )
    db.add(job)
    db.flush()

    return PresignResponse(
        upload_job_id=job.id,
        document_id=doc.id,
        version_id=version.id,
        object_key=object_key,
        upload_url=f"/v1/upload-jobs/{job.id}/content",
    )


@router.put("/upload-jobs/{job_id}/content", response_model=UploadJobOut)
async def upload_content(
    job_id: str,
    file: UploadFile = File(...),
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> UploadJobOut:
    job = db.scalar(
        select(UploadJob).where(UploadJob.id == job_id, UploadJob.tenant_id == auth.tenant_id)
    )
    if job is None:
        raise AppError(ErrorCode.NOT_FOUND, "upload job not found", status_code=404)
    if job.status not in {"created", "uploaded"}:
        raise AppError(
            ErrorCode.CONFLICT,
            f"job status {job.status} not uploadable",
            status_code=409,
        )

    data = await file.read()
    storage = get_storage()
    storage.put_bytes(job.object_key, data)
    checksum = storage.sha256(data)

    job.size_bytes = len(data)
    job.status = "uploaded"
    if file.content_type:
        job.content_type = file.content_type

    version = db.scalar(select(DocumentVersion).where(DocumentVersion.id == job.version_id))
    if version is not None:
        version.size_bytes = len(data)
        version.checksum_sha256 = checksum
        version.status = "uploaded"
        if file.content_type:
            version.content_type = file.content_type

    return _job_out(job)


@router.post("/upload-jobs/{job_id}/complete", response_model=UploadJobOut)
def complete_upload(
    job_id: str,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> UploadJobOut:
    job = db.scalar(
        select(UploadJob).where(UploadJob.id == job_id, UploadJob.tenant_id == auth.tenant_id)
    )
    if job is None:
        raise AppError(ErrorCode.NOT_FOUND, "upload job not found", status_code=404)
    if job.status != "uploaded":
        raise AppError(ErrorCode.CONFLICT, "object not uploaded yet", status_code=409)
    if not get_storage().exists(job.object_key):
        raise AppError(ErrorCode.CONFLICT, "object missing in storage", status_code=409)

    job.status = "queued"
    doc = db.scalar(select(Document).where(Document.id == job.document_id))
    if doc is not None:
        doc.status = "queued"
    version = db.scalar(select(DocumentVersion).where(DocumentVersion.id == job.version_id))
    if version is not None:
        version.status = "queued"

    db.add(
        AuditEvent(
            tenant_id=auth.tenant_id,
            actor_id=auth.user_id,
            action="upload.completed",
            resource_type="upload_job",
            resource_id=job.id,
            detail=json.dumps({"document_id": job.document_id}),
        )
    )
    db.flush()

    # Personal/dev profile: process inline so API clients reach indexed without a separate worker.
    if get_settings().profile == "personal":
        try:
            process_upload_job(db, job.id, actor_id=auth.user_id)
        except Exception as exc:  # noqa: BLE001
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                f"ingest failed: {exc}",
                status_code=500,
            ) from exc

    db.refresh(job)
    return _job_out(job)


@router.post("/upload-jobs/{job_id}/process", response_model=UploadJobOut)
def process_job(
    job_id: str,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> UploadJobOut:
    job = db.scalar(
        select(UploadJob).where(UploadJob.id == job_id, UploadJob.tenant_id == auth.tenant_id)
    )
    if job is None:
        raise AppError(ErrorCode.NOT_FOUND, "upload job not found", status_code=404)
    try:
        process_upload_job(db, job.id, actor_id=auth.user_id)
    except ValueError as exc:
        raise AppError(ErrorCode.CONFLICT, str(exc), status_code=409) from exc
    except Exception as exc:  # noqa: BLE001
        raise AppError(ErrorCode.INTERNAL_ERROR, f"ingest failed: {exc}", status_code=500) from exc
    db.refresh(job)
    return _job_out(job)


@router.get("/upload-jobs/{job_id}", response_model=UploadJobOut)
def get_upload_job(
    job_id: str,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> UploadJobOut:
    job = db.scalar(
        select(UploadJob).where(UploadJob.id == job_id, UploadJob.tenant_id == auth.tenant_id)
    )
    if job is None:
        raise AppError(ErrorCode.NOT_FOUND, "upload job not found", status_code=404)
    return _job_out(job)
