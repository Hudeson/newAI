from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any

import httpx

from shared.config import get_settings


@dataclass(frozen=True)
class CompletionResult:
    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    degraded: bool = False
    detail: dict[str, Any] | None = None


def _estimate_tokens(text: str) -> int:
    return max(len(text.split()), 1)


def local_extractive_answer(
    *,
    prompt: str,
    context_blocks: list[str],
    provider: str,
    model: str,
) -> CompletionResult:
    if not context_blocks:
        text = "I could not find authorized evidence for that question."
    else:
        bullets = "\n".join(f"- {b.strip()}" for b in context_blocks[:5] if b.strip())
        prefix = "[local] "
        text = (
            f"{prefix}Based on your authorized knowledge base:\n{bullets}\n\n"
            f"(Question: {prompt.strip()[:240]} · route={provider}/{model})"
        )
    return CompletionResult(
        text=text,
        provider=provider or "local",
        model=model or "local-extractive",
        input_tokens=_estimate_tokens(prompt) + sum(_estimate_tokens(b) for b in context_blocks),
        output_tokens=_estimate_tokens(text),
        degraded=False,
        detail={"mode": "extractive"},
    )


def openai_compatible_chat(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    timeout: float = 60.0,
) -> CompletionResult:
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        url = f"{root}/chat/completions"
    else:
        url = f"{root}/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "temperature": 0.2}
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    text = (message.get("content") or "").strip()
    usage = data.get("usage") or {}
    return CompletionResult(
        text=text or "(empty model response)",
        provider="openai_compatible",
        model=model,
        input_tokens=int(usage.get("prompt_tokens") or _estimate_tokens(json.dumps(messages))),
        output_tokens=int(usage.get("completion_tokens") or _estimate_tokens(text)),
        detail={"id": data.get("id")},
    )


def ollama_chat(
    *,
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    timeout: float = 120.0,
) -> CompletionResult:
    url = f"{base_url.rstrip('/')}/api/chat"
    payload = {"model": model, "messages": messages, "stream": False}
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    message = data.get("message") or {}
    text = (message.get("content") or "").strip()
    prompt_eval = int(data.get("prompt_eval_count") or 0)
    eval_count = int(data.get("eval_count") or 0)
    return CompletionResult(
        text=text or "(empty ollama response)",
        provider="ollama",
        model=model,
        input_tokens=prompt_eval or _estimate_tokens(json.dumps(messages)),
        output_tokens=eval_count or _estimate_tokens(text),
        detail={"done": data.get("done")},
    )


def seal_secret(plaintext: str, *, secret: str) -> str:
    """Lightweight reversible seal (XOR + base64). Prefer vault in production."""
    key = hashlib.sha256(secret.encode("utf-8")).digest()
    raw = plaintext.encode("utf-8")
    out = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
    return base64.urlsafe_b64encode(out).decode("ascii")


def unseal_secret(token: str, *, secret: str) -> str:
    key = hashlib.sha256(secret.encode("utf-8")).digest()
    raw = base64.urlsafe_b64decode(token.encode("ascii"))
    out = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
    return out.decode("utf-8")


def build_ask_messages(*, prompt: str, context_blocks: list[str]) -> list[dict[str, str]]:
    evidence = "\n\n".join(
        f"[{i + 1}] {b.strip()}" for i, b in enumerate(context_blocks[:8]) if b.strip()
    )
    system = (
        "You are a knowledge-base assistant. Answer only from the provided evidence. "
        "If evidence is insufficient, say you cannot find authorized evidence. "
        "Cite evidence numbers like [1] when relevant."
    )
    user = f"Evidence:\n{evidence or '(none)'}\n\nQuestion: {prompt.strip()}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_learn_messages(*, text: str) -> list[dict[str, str]]:
    system = (
        "You extract structured learning notes from a document. "
        "Respond with JSON only: "
        '{"summary":"...","outline":["..."],"key_points":["..."]}.'
    )
    user = f"Document:\n{text[:12000]}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_graph_extract_messages(*, title: str, text: str) -> list[dict[str, str]]:
    system = (
        "You extract a knowledge graph from a document chunk. "
        "Respond with JSON only: "
        '{"entities":[{"name":"...","type":"person|organization|product|concept|'
        'location|event|document_ref|other","aliases":["..."]}],'
        '"relations":[{"subject":"...","predicate":"related_to|part_of|works_at|'
        'authored_by|depends_on|defines|references|located_in|occurs_in|synonym_of",'
        '"object":"...","evidence":"..."}]}.'
        " Use only facts present in the text. Prefer controlled types and predicates."
    )
    user = f"Title: {title or '(untitled)'}\n\nChunk:\n{(text or '')[:8000]}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]

def ping_provider(
    *,
    provider: str,
    model: str,
    api_key: str = "",
    base_url: str = "",
) -> dict[str, Any]:
    settings = get_settings()
    messages = [{"role": "user", "content": "Reply with the single word: pong"}]
    if provider in {"openai_compatible", "openai"}:
        result = openai_compatible_chat(
            base_url=base_url or settings.llm_base_url,
            api_key=api_key or settings.llm_api_key,
            model=model or settings.llm_model,
            messages=messages,
            timeout=settings.llm_timeout_seconds,
        )
    elif provider == "ollama":
        result = ollama_chat(
            base_url=base_url or settings.ollama_base_url,
            model=model or settings.ollama_model,
            messages=messages,
            timeout=settings.llm_timeout_seconds,
        )
    else:
        result = local_extractive_answer(
            prompt="ping",
            context_blocks=["pong"],
            provider="local",
            model="local-extractive",
        )
    return {
        "ok": True,
        "provider": result.provider,
        "model": result.model,
        "preview": result.text[:120],
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }
