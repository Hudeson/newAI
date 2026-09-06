from __future__ import annotations

import json
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.db.models import AuditEvent, Chunk, Document, LearningReport, Workspace
from shared.ingest import tokenize
from shared.llm import record_usage


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class LearnResult:
    report_id: str
    document_id: str
    status: str
    summary: str
    outline: list[str]
    key_points: list[str]


def build_learning_payload(text: str) -> tuple[str, list[str], list[str]]:
    """Extractive local learner (no external LLM required)."""
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return "", [], []

    headings = [m.group(2).strip() for m in _HEADING_RE.finditer(text)]
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    # Prefer non-heading paragraphs for summary/key points.
    body = [p for p in paragraphs if not _HEADING_RE.match(p)]
    if not body:
        body = paragraphs

    summary = body[0]
    if len(summary) > 400:
        summary = summary[:397].rstrip() + "..."

    outline = headings[:12] if headings else [p[:120] for p in body[:6]]

    key_points: list[str] = []
    for p in body[:8]:
        # Sentence-ish split
        parts = re.split(r"(?<=[。.!?;])\s+", p)
        for part in parts:
            s = part.strip()
            if len(s) < 20:
                continue
            key_points.append(s if len(s) <= 200 else s[:197].rstrip() + "...")
            if len(key_points) >= 5:
                break
        if len(key_points) >= 5:
            break
    if not key_points and body:
        key_points = [body[0][:200]]

    return summary, outline, key_points


def learn_document(
    db: Session,
    *,
    tenant_id: str,
    document_id: str,
    version_id: str | None = None,
    actor_id: str | None = None,
) -> LearnResult:
    doc = db.scalar(
        select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
    )
    if doc is None:
        raise ValueError("document not found")

    chunks_q = select(Chunk).where(
        Chunk.tenant_id == tenant_id,
        Chunk.document_id == document_id,
        Chunk.status == "active",
    )
    if version_id:
        chunks_q = chunks_q.where(Chunk.version_id == version_id)
    chunks = db.scalars(chunks_q.order_by(Chunk.ordinal)).all()
    if not chunks:
        raise ValueError("document has no indexed chunks")

    version_id = version_id or chunks[0].version_id
    text = "\n\n".join(c.content for c in chunks)
    summary, outline, key_points = build_learning_payload(text)

    workspace = db.scalar(select(Workspace).where(Workspace.id == doc.workspace_id))
    publish_mode = workspace.publish_mode if workspace else "auto"
    status = "published" if publish_mode == "auto" else "draft"

    existing = db.scalar(
        select(LearningReport).where(
            LearningReport.document_id == document_id,
            LearningReport.version_id == version_id,
        )
    )
    if existing is None:
        report = LearningReport(
            tenant_id=tenant_id,
            workspace_id=doc.workspace_id,
            document_id=document_id,
            version_id=version_id,
            status=status,
            summary=summary,
            outline_json=json.dumps(outline, ensure_ascii=False),
            key_points_json=json.dumps(key_points, ensure_ascii=False),
            provider="local-extractive",
        )
        db.add(report)
    else:
        report = existing
        report.status = status
        report.summary = summary
        report.outline_json = json.dumps(outline, ensure_ascii=False)
        report.key_points_json = json.dumps(key_points, ensure_ascii=False)
        report.provider = "local-extractive"

    if status == "published":
        doc.status = "published"
    elif doc.status == "indexed":
        doc.status = "learned"

    in_tokens = len(tokenize(text))
    out_tokens = len(tokenize(summary)) + sum(len(tokenize(x)) for x in outline + key_points)
    record_usage(
        db,
        tenant_id=tenant_id,
        user_id=actor_id,
        operation="learn",
        provider="local",
        model="local-extractive",
        input_tokens=in_tokens,
        output_tokens=out_tokens,
        detail={"document_id": document_id, "version_id": version_id},
    )
    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="document.learned",
            resource_type="document",
            resource_id=document_id,
            detail=json.dumps({"report_status": status, "version_id": version_id}),
        )
    )
    db.flush()
    return LearnResult(
        report_id=report.id,
        document_id=document_id,
        status=report.status,
        summary=summary,
        outline=outline,
        key_points=key_points,
    )
