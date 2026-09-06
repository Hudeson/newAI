from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.acl import readable_document_ids
from shared.db.models import Chunk
from shared.ingest import cosine, embed_text


@dataclass(frozen=True)
class SearchHit:
    chunk_id: str
    document_id: str
    version_id: str
    workspace_id: str
    ordinal: int
    score: float
    content: str


def search_chunks(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    query: str,
    limit: int = 8,
    workspace_ids: list[str] | None = None,
) -> list[SearchHit]:
    """Hybrid-ready local vector search. Tenant + ACL filters are mandatory."""
    if not tenant_id:
        raise ValueError("tenant_id is required")
    if not user_id:
        raise ValueError("user_id is required")
    if not query.strip():
        return []

    allowed = readable_document_ids(
        db, tenant_id=tenant_id, user_id=user_id, workspace_ids=workspace_ids
    )
    if not allowed:
        return []

    # Always constrain by tenant_id — never scroll the full collection.
    rows = db.scalars(
        select(Chunk).where(
            Chunk.tenant_id == tenant_id,
            Chunk.status == "active",
            Chunk.document_id.in_(allowed),
        )
    ).all()

    qvec = embed_text(query)
    scored: list[SearchHit] = []
    for row in rows:
        try:
            emb = json.loads(row.embedding_json or "[]")
        except json.JSONDecodeError:
            continue
        if not isinstance(emb, list) or not emb:
            continue
        score = cosine(qvec, [float(x) for x in emb])
        if score <= 0:
            continue
        scored.append(
            SearchHit(
                chunk_id=row.id,
                document_id=row.document_id,
                version_id=row.version_id,
                workspace_id=row.workspace_id,
                ordinal=row.ordinal,
                score=score,
                content=row.content,
            )
        )
    scored.sort(key=lambda h: h.score, reverse=True)
    return scored[: max(0, min(limit, 50))]
