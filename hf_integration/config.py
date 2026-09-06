"""Environment-driven settings for Hugging Face access."""

from __future__ import annotations

import os
from dataclasses import dataclass


DEFAULT_CHAT_MODEL = "HuggingFaceH4/zephyr-7b-beta"
DEFAULT_EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_PROVIDER = "auto"
DEFAULT_TIMEOUT = 60.0


@dataclass(frozen=True)
class Settings:
    """Runtime configuration resolved from environment variables."""

    token: str | None = None
    endpoint: str | None = None
    model: str = DEFAULT_CHAT_MODEL
    embed_model: str = DEFAULT_EMBED_MODEL
    provider: str = DEFAULT_PROVIDER
    timeout: float = DEFAULT_TIMEOUT

    @property
    def has_token(self) -> bool:
        return bool(self.token)


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def load_settings(
    *,
    token: str | None = None,
    endpoint: str | None = None,
    model: str | None = None,
    embed_model: str | None = None,
    provider: str | None = None,
    timeout: float | None = None,
) -> Settings:
    """Load settings, allowing explicit overrides to win over env vars."""

    raw_timeout = _env("HF_TIMEOUT")
    resolved_timeout = (
        timeout
        if timeout is not None
        else float(raw_timeout)
        if raw_timeout is not None
        else DEFAULT_TIMEOUT
    )

    return Settings(
        token=token if token is not None else _env("HF_TOKEN") or _env("HUGGINGFACE_HUB_TOKEN"),
        endpoint=endpoint if endpoint is not None else _env("HF_ENDPOINT"),
        model=model or _env("HF_MODEL", DEFAULT_CHAT_MODEL) or DEFAULT_CHAT_MODEL,
        embed_model=(
            embed_model
            or _env("HF_EMBED_MODEL", DEFAULT_EMBED_MODEL)
            or DEFAULT_EMBED_MODEL
        ),
        provider=provider or _env("HF_PROVIDER", DEFAULT_PROVIDER) or DEFAULT_PROVIDER,
        timeout=resolved_timeout,
    )


def apply_hub_endpoint(endpoint: str | None) -> None:
    """Apply a Hub API mirror to the process environment when provided."""

    if not endpoint:
        return
    os.environ["HF_ENDPOINT"] = endpoint.rstrip("/")
