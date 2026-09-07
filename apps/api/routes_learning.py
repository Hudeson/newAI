from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import AuthContext, get_current_auth
from shared.acl import can_read_document
from shared.db import get_db
from shared.db.models import Document, LearningReport
from shared.errors import AppError, ErrorCode
from shared.learn import learn_document
from shared.quota import enforce_operation_quota

router = APIRouter(prefix="/v1", tags=["learning"])


class LearningReportOut(BaseModel):
    id: str
    document_id: str
    version_id: str
    workspace_id: str
    status: str
    summary: str
    outline: list[str]
    key_points: list[str]
    provider: str


def _report_out(report: LearningReport) -> LearningReportOut:
    return LearningReportOut(
        id=report.id,
        document_id=report.document_id,
        version_id=report.version_id,
        workspace_id=report.workspace_id,
        status=report.status,
        summary=report.summary,
        outline=json.loads(report.outline_json or "[]"),
        key_points=json.loads(report.key_points_json or "[]"),
        provider=report.provider,
    )


@router.get("/documents/{document_id}/learning", response_model=LearningReportOut)
def get_learning_report(
    document_id: str,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> LearningReportOut:
    doc = db.scalar(
        select(Document).where(Document.id == document_id, Document.tenant_id == auth.tenant_id)
    )
    if doc is None or not can_read_document(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, document_id=document_id
    ):
        raise AppError(ErrorCode.NOT_FOUND, "document not found", status_code=404)

    report = db.scalar(
        select(LearningReport)
        .where(
            LearningReport.tenant_id == auth.tenant_id,
            LearningReport.document_id == document_id,
        )
        .order_by(LearningReport.created_at.desc())
    )
    if report is None:
        raise AppError(ErrorCode.NOT_FOUND, "learning report not found", status_code=404)
    return _report_out(report)


@router.post("/documents/{document_id}/learn", response_model=LearningReportOut)
def trigger_learn(
    document_id: str,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> LearningReportOut:
    doc = db.scalar(
        select(Document).where(Document.id == document_id, Document.tenant_id == auth.tenant_id)
    )
    if doc is None or not can_read_document(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, document_id=document_id
    ):
        raise AppError(ErrorCode.NOT_FOUND, "document not found", status_code=404)
    enforce_operation_quota(db, tenant_id=auth.tenant_id, operation="learn")
    try:
        result = learn_document(
            db,
            tenant_id=auth.tenant_id,
            document_id=document_id,
            actor_id=auth.user_id,
        )
    except ValueError as exc:
        raise AppError(ErrorCode.CONFLICT, str(exc), status_code=409) from exc

    report = db.scalar(select(LearningReport).where(LearningReport.id == result.report_id))
    assert report is not None
    return _report_out(report)


class PublishRequest(BaseModel):
    status: str = Field(pattern=r"^(draft|published)$")


@router.post("/documents/{document_id}/learning/publish", response_model=LearningReportOut)
def publish_learning(
    document_id: str,
    body: PublishRequest,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> LearningReportOut:
    doc = db.scalar(
        select(Document).where(Document.id == document_id, Document.tenant_id == auth.tenant_id)
    )
    if doc is None or not can_read_document(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, document_id=document_id
    ):
        raise AppError(ErrorCode.NOT_FOUND, "document not found", status_code=404)
    report = db.scalar(
        select(LearningReport)
        .where(
            LearningReport.tenant_id == auth.tenant_id,
            LearningReport.document_id == document_id,
        )
        .order_by(LearningReport.created_at.desc())
    )
    if report is None:
        raise AppError(ErrorCode.NOT_FOUND, "learning report not found", status_code=404)
    report.status = body.status
    if body.status == "published":
        doc.status = "published"
    db.flush()
    return _report_out(report)
