from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.acl import readable_document_ids
from shared.db.models import AuditEvent, Chunk, Document
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
    graph_augmented: bool = False
    web_search_augmented: bool = False
    web_citations: list[dict] | None = None


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
    graph_augment: bool = False,
    web_search: bool = False,
) -> AskResult:
    from shared.config import get_settings
    from shared.graph import serialize_graph_context
    from shared.web_search import serialize_web_context, web_hits_to_dict, web_search as run_web_search

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
    graph_blocks: list[str] = []
    if graph_augment:
        graph_blocks = serialize_graph_context(
            db, tenant_id=tenant_id, user_id=user_id, question=question
        )
        if graph_blocks:
            context_blocks = [
                "[知识图谱]\n" + b for b in graph_blocks
            ] + context_blocks

    web_hits = []
    web_blocks: list[str] = []
    if web_search and get_settings().web_search_enabled:
        try:
            web_hits = run_web_search(question, limit=min(limit, 5), education=False)
            web_blocks = serialize_web_context(web_hits)
            if web_blocks:
                context_blocks = web_blocks + context_blocks
        except Exception:  # noqa: BLE001 - web search is best-effort for Ask
            web_hits = []
            web_blocks = []

    # Route by highest sensitivity among cited documents (L4 > L1).
    sensitivity = "L2"
    if safe_hits:
        docs = db.scalars(
            select(Document).where(
                Document.tenant_id == tenant_id,
                Document.id.in_({h.document_id for h in safe_hits}),
            )
        ).all()
        order = {"L1": 1, "L2": 2, "L3": 3, "L4": 4}
        if docs:
            sensitivity = max(docs, key=lambda d: order.get(d.sensitivity, 2)).sensitivity

    answer = local_complete(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        prompt=question,
        context_blocks=context_blocks,
        operation="ask",
        sensitivity=sensitivity,
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
                f'"answer_tokens":{len(tokenize(answer))},'
                f'"graph_augmented":{str(bool(graph_augment and graph_blocks)).lower()},'
                f'"web_search_augmented":{str(bool(web_blocks)).lower()}}}'
            ),
        )
    )
    db.flush()
    return AskResult(
        answer=answer,
        citations=citations,
        graph_augmented=bool(graph_augment and graph_blocks),
        web_search_augmented=bool(web_blocks),
        web_citations=web_hits_to_dict(web_hits) if web_hits else [],
    )
