from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from shared.config import get_settings
from shared.credentials import resolve_connection
from shared.db.models import UsageLedger
from shared.gateway import (
    CompletionResult,
    build_ask_messages,
    build_learn_messages,
    local_extractive_answer,
    ollama_chat,
    openai_compatible_chat,
)
from shared.logging import get_logger
from shared.policy import resolve_route

logger = get_logger("llm")


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


def _dispatch(
    *,
    provider: str,
    model: str,
    api_key: str,
    base_url: str,
    messages: list[dict[str, str]],
    prompt: str,
    context_blocks: list[str],
) -> CompletionResult:
    settings = get_settings()
    timeout = settings.llm_timeout_seconds
    if provider == "openai_compatible":
        if not api_key:
            return local_extractive_answer(
                prompt=prompt,
                context_blocks=context_blocks,
                provider="local",
                model="local-extractive",
            )
        return openai_compatible_chat(
            base_url=base_url,
            api_key=api_key,
            model=model,
            messages=messages,
            timeout=timeout,
        )
    if provider == "ollama":
        return ollama_chat(
            base_url=base_url,
            model=model,
            messages=messages,
            timeout=timeout,
        )
    return local_extractive_answer(
        prompt=prompt,
        context_blocks=context_blocks,
        provider=provider or "local",
        model=model or "local-extractive",
    )


def gateway_complete(
    db: Session,
    *,
    tenant_id: str,
    user_id: str | None,
    prompt: str,
    context_blocks: list[str],
    operation: str = "ask",
    sensitivity: str = "L2",
    purpose: str = "ask",
) -> str:
    route_provider, route_model = resolve_route(db, tenant_id=tenant_id, sensitivity=sensitivity)
    provider, model, api_key, base_url = resolve_connection(
        db,
        tenant_id=tenant_id,
        provider=route_provider,
        model=route_model,
    )
    if purpose == "learn":
        messages = build_learn_messages(text="\n\n".join(context_blocks) or prompt)
    else:
        messages = build_ask_messages(prompt=prompt, context_blocks=context_blocks)

    degraded = False
    try:
        result = _dispatch(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            messages=messages,
            prompt=prompt,
            context_blocks=context_blocks,
        )
        if provider in {"openai_compatible", "ollama"} and result.provider == "local":
            degraded = True
    except Exception as exc:  # noqa: BLE001 - degrade to local
        logger.warning("llm_gateway_fallback", provider=provider, error=str(exc)[:300])
        result = local_extractive_answer(
            prompt=prompt,
            context_blocks=context_blocks,
            provider="local",
            model="local-extractive",
        )
        degraded = True

    record_usage(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        operation=operation,
        provider=result.provider,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        detail={
            "context_blocks": len(context_blocks),
            "sensitivity": sensitivity,
            "route_provider": route_provider,
            "route_model": route_model,
            "degraded": degraded,
            "purpose": purpose,
            **(result.detail or {}),
        },
    )
    return result.text


def local_complete(
    db: Session,
    *,
    tenant_id: str,
    user_id: str | None,
    prompt: str,
    context_blocks: list[str],
    operation: str = "ask",
    sensitivity: str = "L2",
) -> str:
    """Backward-compatible entrypoint used by Ask."""
    return gateway_complete(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        prompt=prompt,
        context_blocks=context_blocks,
        operation=operation,
        sensitivity=sensitivity,
        purpose="ask",
    )


def learn_with_gateway(
    db: Session,
    *,
    tenant_id: str,
    user_id: str | None,
    text: str,
    sensitivity: str = "L2",
) -> tuple[str, list[str], list[str], str] | None:
    """Return (summary, outline, key_points, provider) or None to fall back."""
    route_provider, route_model = resolve_route(db, tenant_id=tenant_id, sensitivity=sensitivity)
    provider, model, api_key, base_url = resolve_connection(
        db,
        tenant_id=tenant_id,
        provider=route_provider,
        model=route_model,
    )
    if provider == "local":
        return None
    if provider == "openai_compatible" and not api_key:
        return None

    messages = build_learn_messages(text=text)
    settings = get_settings()
    try:
        if provider == "openai_compatible":
            result = openai_compatible_chat(
                base_url=base_url,
                api_key=api_key,
                model=model,
                messages=messages,
                timeout=settings.llm_timeout_seconds,
            )
        elif provider == "ollama":
            result = ollama_chat(
                base_url=base_url,
                model=model,
                messages=messages,
                timeout=settings.llm_timeout_seconds,
            )
        else:
            return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("learn_gateway_failed", provider=provider, error=str(exc)[:300])
        return None

    cleaned = result.text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    summary = str(data.get("summary") or "").strip()
    outline = [str(x).strip() for x in (data.get("outline") or []) if str(x).strip()]
    key_points = [str(x).strip() for x in (data.get("key_points") or []) if str(x).strip()]
    if not summary:
        return None
    record_usage(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        operation="learn",
        provider=result.provider,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        detail={"sensitivity": sensitivity, "purpose": "learn"},
    )
    return summary, outline, key_points, f"{result.provider}/{result.model}"
