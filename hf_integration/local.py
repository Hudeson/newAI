"""Optional local transformers backend (no HF Inference token required)."""

from __future__ import annotations

import logging
import warnings
from functools import lru_cache
from typing import Any, Sequence

logging.getLogger("transformers").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", message=".*generation_config.*")
warnings.filterwarnings("ignore", message=".*max_new_tokens.*")
warnings.filterwarnings("ignore", message=".*clean_up_tokenization_spaces.*")


class LocalBackendUnavailable(RuntimeError):
    """Raised when torch/transformers are not installed."""


def _require_transformers() -> tuple[Any, Any]:
    try:
        import torch
        from transformers import pipeline
    except ImportError as exc:  # pragma: no cover - exercised in real envs
        raise LocalBackendUnavailable(
            "Local provider needs `torch` and `transformers`. "
            "Install with: python3 -m pip install torch transformers "
            "(CPU torch: --index-url https://download.pytorch.org/whl/cpu)"
        ) from exc
    return torch, pipeline


@lru_cache(maxsize=4)
def _text_generator(model_id: str) -> Any:
    _, pipeline = _require_transformers()
    pipe = pipeline(
        "text-generation",
        model=model_id,
        tokenizer=model_id,
        device=-1,
    )
    if getattr(pipe, "tokenizer", None) is not None:
        pipe.tokenizer.clean_up_tokenization_spaces = False
    return pipe


@lru_cache(maxsize=2)
def _feature_extractor(model_id: str) -> Any:
    _, pipeline = _require_transformers()
    return pipeline(
        "feature-extraction",
        model=model_id,
        tokenizer=model_id,
        device=-1,
    )


def local_generate(
    prompt: str,
    *,
    model: str,
    max_new_tokens: int = 32,
    temperature: float = 0.7,
    return_full_text: bool = False,
) -> str:
    gen = _text_generator(model)
    do_sample = temperature is not None and temperature > 0
    outputs = gen(
        prompt,
        max_new_tokens=max_new_tokens,
        do_sample=do_sample,
        temperature=max(temperature, 1e-5) if do_sample else None,
        pad_token_id=gen.tokenizer.eos_token_id,
    )
    text = outputs[0]["generated_text"]
    if return_full_text:
        return text
    if text.startswith(prompt):
        return text[len(prompt) :]
    return text


def local_chat(
    messages: Sequence[dict[str, str]],
    *,
    model: str,
    max_tokens: int = 64,
    temperature: float = 0.7,
) -> str:
    prompt = _messages_to_prompt(messages)
    return local_generate(
        prompt,
        model=model,
        max_new_tokens=max_tokens,
        temperature=temperature,
        return_full_text=False,
    ).strip()


def local_embed(
    text: str | Sequence[str],
    *,
    model: str,
    normalize: bool = True,
) -> list[list[float]]:
    import torch

    _require_transformers()
    extractor = _feature_extractor(model)
    inputs = [text] if isinstance(text, str) else list(text)
    vectors: list[list[float]] = []
    for item in inputs:
        features = extractor(item)
        # pipeline returns nested lists: [tokens][hidden]
        tensor = torch.tensor(features[0], dtype=torch.float32)
        pooled = tensor.mean(dim=0)
        if normalize:
            pooled = pooled / (pooled.norm() + 1e-12)
        vectors.append(pooled.tolist())
    return vectors


def _messages_to_prompt(messages: Sequence[dict[str, str]]) -> str:
    lines: list[str] = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if role == "system":
            lines.append(f"System: {content}")
        elif role == "assistant":
            lines.append(f"Assistant: {content}")
        else:
            lines.append(f"User: {content}")
    lines.append("Assistant:")
    return "\n".join(lines)


def clear_local_caches() -> None:
    _text_generator.cache_clear()
    _feature_extractor.cache_clear()
