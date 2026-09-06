from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from shared.db.models import UsageLedger
from shared.ingest import tokenize


def record_usage(
    db: Session,
    *,
    tenant_id: str,
    user_id: str | None,
    operation: str,
    provider: str = "local",
    model: str = "local-extractive",
    input_tokens: int = 0,
    output_tokens: int = 0,
    detail: dict[str, Any] | None = None,
) -> UsageLedger:
    row = UsageLedger(
        tenant_id=tenant_id,
        user_id=user_id,
        operation=operation,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        detail=json.dumps(detail or {}, ensure_ascii=False),
    )
    db.add(row)
    db.flush()
    return row


def local_complete(
    db: Session,
    *,
    tenant_id: str,
    user_id: str | None,
    prompt: str,
    context_blocks: list[str],
    operation: str = "ask",
) -> str:
    """Minimal local 'LLM' gateway: stitch an answer from retrieved context."""
    if not context_blocks:
        answer = "I could not find authorized evidence for that question."
    else:
        bullets = "\n".join(f"- {b.strip()}" for b in context_blocks[:5] if b.strip())
        answer = (
            f"Based on your authorized knowledge base:\n{bullets}\n\n"
            f"(Question: {prompt.strip()[:240]})"
        )
    record_usage(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        operation=operation,
        provider="local",
        model="local-extractive",
        input_tokens=len(tokenize(prompt)) + sum(len(tokenize(b)) for b in context_blocks),
        output_tokens=len(tokenize(answer)),
        detail={"context_blocks": len(context_blocks)},
    )
    return answer
