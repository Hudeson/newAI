from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.acl import readable_document_ids
from shared.db.models import AuditEvent, Chunk
from shared.ingest import tokenize
from shared.llm import local_complete
from shared.search import SearchHit, search_chunks


@dataclass(frozen=True)
class Citation:
    chunk_id: str
    document_id: str
    version_id: str
    workspace_id: str
    ordinal: int
    score: float
    snippet: str


@dataclass(frozen=True)
class AskResult:
    answer: str
    citations: list[Citation]


def validate_citations(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    chunk_ids: list[str],
) -> list[Chunk]:
    """Ensure every cited chunk belongs to the tenant and is ACL-readable."""
    if not chunk_ids:
        return []
    allowed = readable_document_ids(db, tenant_id=tenant_id, user_id=user_id)
    if not allowed:
        return []
    rows = db.scalars(
        select(Chunk).where(
            Chunk.tenant_id == tenant_id,
            Chunk.id.in_(chunk_ids),
            Chunk.status == "active",
            Chunk.document_id.in_(allowed),
        )
    ).all()
    by_id = {r.id: r for r in rows}
    # Preserve caller order; drop unauthorized ids.
    return [by_id[cid] for cid in chunk_ids if cid in by_id]


def ask(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    question: str,
    limit: int = 5,
) -> AskResult:
    hits: list[SearchHit] = search_chunks(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        query=question,
        limit=limit,
    )
    # Defense in depth: re-validate chunk ACL before citing.
    valid_chunks = validate_citations(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        chunk_ids=[h.chunk_id for h in hits],
    )
    valid_ids = {c.id for c in valid_chunks}
    safe_hits = [h for h in hits if h.chunk_id in valid_ids]

    context_blocks = [h.content for h in safe_hits]
    answer = local_complete(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        prompt=question,
        context_blocks=context_blocks,
        operation="ask",
    )
    citations = [
        Citation(
            chunk_id=h.chunk_id,
            document_id=h.document_id,
            version_id=h.version_id,
            workspace_id=h.workspace_id,
            ordinal=h.ordinal,
            score=h.score,
            snippet=h.content[:280],
        )
        for h in safe_hits
    ]
    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_id=user_id,
            action="ask.query",
            resource_type="ask",
            resource_id="",
            detail=(
                f'{{"question_len":{len(question)},'
                f'"citation_count":{len(citations)},'
                f'"answer_tokens":{len(tokenize(answer))}}}'
            ),
        )
    )
    db.flush()
    return AskResult(answer=answer, citations=citations)
