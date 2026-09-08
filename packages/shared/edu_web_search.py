"""Education auto web-search and import into packs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from shared.config import get_settings
from shared.db.models import AuditEvent
from shared.edu_official import SyncResult, fetch_feed_payload, sync_official_source
from shared.education import require_edu_enabled
from shared.errors import AppError, ErrorCode
from shared.web_search import (
    WebHit,
    build_education_query,
    web_hits_to_dict,
    web_search,
)


@dataclass
class EduWebSearchResult:
    query: str
    provider: str
    hits: list[WebHit] = field(default_factory=list)
    imported: list[SyncResult] = field(default_factory=list)


def search_education_web(
    *,
    query: str,
    subject: str | None = None,
    stage: str | None = None,
    grade: int | None = None,
    limit: int = 5,
) -> EduWebSearchResult:
    require_edu_enabled()
    settings = get_settings()
    if not settings.edu_web_search_enabled:
        raise AppError(ErrorCode.FORBIDDEN, "education web search disabled", status_code=403)
    expanded = build_education_query(query=query, subject=subject, stage=stage, grade=grade)
    hits = web_search(
        expanded,
        limit=limit,
        education=True,
        provider=settings.edu_web_search_provider or settings.web_search_provider,
    )
    return EduWebSearchResult(
        query=expanded,
        provider=settings.edu_web_search_provider or settings.web_search_provider,
        hits=hits,
    )


def import_web_hits(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    workspace_id: str,
    hits: list[WebHit],
    accept_license: bool,
    subject: str | None = None,
    stage: str | None = None,
) -> list[SyncResult]:
    """Fetch allowlisted / fixture hits and import via official sync pipeline."""
    require_edu_enabled()
    if not accept_license:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "accept_license=true is required to import web search results",
            status_code=400,
        )
    if not hits:
        return []

    imported: list[SyncResult] = []
    for hit in hits:
        url = hit.url
        # Map fixture search hits to built-in source ids when possible.
        source_id = "live-custom"
        feed_url = url
        if url.startswith("fixture://moe-math"):
            source_id = "fixture-moe-math-g7"
            feed_url = url
        elif url.startswith("fixture://smartedu-chinese"):
            source_id = "fixture-smartedu-chinese-g7"
            feed_url = url
        elif url.startswith("fixture://"):
            # Ensure payload is fetchable before sync
            fetch_feed_payload(feed_url=url)
            source_id = "live-custom"
            feed_url = url
        else:
            # Live page: only sync when live mode enabled inside fetch_feed_payload
            source_id = "live-custom"
            feed_url = url

        try:
            result = sync_official_source(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                workspace_id=workspace_id,
                source_id=source_id,
                accept_license=True,
                feed_url=feed_url,
            )
            imported.append(result)
        except AppError:
            # Skip individual failed URLs; continue others
            continue

    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_id=user_id,
            action="edu.web_search.import",
            resource_type="edu_web_search",
            resource_id="",
            detail=json.dumps(
                {
                    "hit_count": len(hits),
                    "imported": len(imported),
                    "urls": [h.url for h in hits],
                    "subject": subject,
                    "stage": stage,
                },
                ensure_ascii=False,
            ),
        )
    )
    db.commit()
    return imported


def search_and_maybe_import(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    workspace_id: str,
    query: str,
    accept_license: bool,
    auto_import: bool = False,
    subject: str | None = None,
    stage: str | None = None,
    grade: int | None = None,
    limit: int = 5,
) -> dict:
    found = search_education_web(
        query=query, subject=subject, stage=stage, grade=grade, limit=limit
    )
    imported: list[SyncResult] = []
    if auto_import:
        # Prefer fixture / structured feeds first
        ordered = sorted(
            found.hits,
            key=lambda h: (0 if h.url.startswith("fixture://") else 1, -h.score),
        )
        imported = import_web_hits(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            workspace_id=workspace_id,
            hits=ordered[: max(1, min(3, limit))],
            accept_license=accept_license,
            subject=subject,
            stage=stage,
        )
    return {
        "query": found.query,
        "provider": found.provider,
        "hits": web_hits_to_dict(found.hits),
        "auto_import": auto_import,
        "imports": [
            {
                "job_id": r.job_id,
                "source_id": r.source_id,
                "pack_id": r.pack_id,
                "status": r.status,
                "tutorials_imported": r.tutorials_imported,
                "questions_imported": r.questions_imported,
                "points_imported": r.points_imported,
            }
            for r in imported
        ],
    }
