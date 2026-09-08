from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from shared.ask import ask as run_ask
from shared.config import get_settings
from shared.db import get_db
from shared.db.models import UsageLedger
from shared.quota import enforce_operation_quota
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import AuthContext, get_current_auth

router = APIRouter(prefix="/v1", tags=["ask"])


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=5, ge=1, le=20)
    graph_augment: bool | None = None
    web_search: bool | None = None


class CitationOut(BaseModel):
    chunk_id: str
    document_id: str
    version_id: str
    workspace_id: str
    ordinal: int
    score: float
    snippet: str


class WebCitationOut(BaseModel):
    title: str
    url: str
    snippet: str
    provider: str
    score: float = 0.0
    host: str = ""
    allowlisted: bool = False


class AskResponse(BaseModel):
    answer: str
    citations: list[CitationOut]
    graph_augmented: bool = False
    web_search_augmented: bool = False
    web_citations: list[WebCitationOut] = Field(default_factory=list)


class UsageOut(BaseModel):
    id: str
    operation: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int


@router.post("/ask", response_model=AskResponse)
def ask(
    body: AskRequest,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> AskResponse:
    enforce_operation_quota(db, tenant_id=auth.tenant_id, operation="ask")
    settings = get_settings()
    graph_augment = (
        settings.graph_ask_augment_default
        if body.graph_augment is None
        else body.graph_augment
    )
    use_web = (
        settings.ask_web_search_default if body.web_search is None else body.web_search
    )
    result = run_ask(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        question=body.question,
        limit=body.limit,
        graph_augment=graph_augment,
        web_search=use_web,
    )
    return AskResponse(
        answer=result.answer,
        citations=[
            CitationOut(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                version_id=c.version_id,
                workspace_id=c.workspace_id,
                ordinal=c.ordinal,
                score=c.score,
                snippet=c.snippet,
            )
            for c in result.citations
        ],
        graph_augmented=result.graph_augmented,
        web_search_augmented=result.web_search_augmented,
        web_citations=[WebCitationOut(**w) for w in (result.web_citations or [])],
    )


@router.get("/usage", response_model=list[UsageOut])
def list_usage(
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> list[UsageOut]:
    rows = db.scalars(
        select(UsageLedger)
        .where(UsageLedger.tenant_id == auth.tenant_id)
        .order_by(UsageLedger.created_at.desc())
        .limit(50)
    ).all()
    return [
        UsageOut(
            id=r.id,
            operation=r.operation,
            provider=r.provider,
            model=r.model,
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
        )
        for r in rows
    ]
