from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from shared.db import get_db
from shared.db.models import AuditEvent
from shared.llm import record_usage
from shared.quota import enforce_operation_quota
from shared.search import search_chunks
from sqlalchemy.orm import Session

from api.auth import AuthContext, get_current_auth

router = APIRouter(prefix="/v1", tags=["search"])


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=8, ge=1, le=50)


class SearchHitOut(BaseModel):
    chunk_id: str
    document_id: str
    version_id: str
    workspace_id: str
    ordinal: int
    score: float
    content: str


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHitOut]


@router.post("/search", response_model=SearchResponse)
def search(
    body: SearchRequest,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> SearchResponse:
    enforce_operation_quota(db, tenant_id=auth.tenant_id, operation="search")
    hits = search_chunks(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        query=body.query,
        limit=body.limit,
    )
    record_usage(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        operation="search",
        provider="local",
        model="search",
        input_tokens=max(len(body.query.split()), 1),
        output_tokens=len(hits),
        detail={"hit_count": len(hits)},
    )
    db.add(
        AuditEvent(
            tenant_id=auth.tenant_id,
            actor_id=auth.user_id,
            action="search.query",
            resource_type="search",
            resource_id="",
            detail=f'{{"query_len":{len(body.query)},"hit_count":{len(hits)}}}',
        )
    )
    return SearchResponse(
        query=body.query,
        hits=[
            SearchHitOut(
                chunk_id=h.chunk_id,
                document_id=h.document_id,
                version_id=h.version_id,
                workspace_id=h.workspace_id,
                ordinal=h.ordinal,
                score=h.score,
                content=h.content,
            )
            for h in hits
        ],
    )
