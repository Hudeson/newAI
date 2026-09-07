from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.config import get_settings
from shared.db.models import LlmCredential
from shared.errors import AppError, ErrorCode
from shared.gateway import seal_secret, unseal_secret


def _secret() -> str:
    settings = get_settings()
    return settings.credentials_secret or settings.jwt_secret


def list_credentials(db: Session, *, tenant_id: str) -> list[LlmCredential]:
    return list(
        db.scalars(
            select(LlmCredential)
            .where(LlmCredential.tenant_id == tenant_id)
            .order_by(LlmCredential.provider.asc())
        ).all()
    )


def upsert_credential(
    db: Session,
    *,
    tenant_id: str,
    provider: str,
    api_key: str | None = None,
    base_url: str = "",
    default_model: str = "",
    clear_key: bool = False,
) -> LlmCredential:
    if provider not in {"openai_compatible", "ollama", "local"}:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            f"unsupported provider: {provider}",
            status_code=400,
        )
    row = db.scalar(
        select(LlmCredential).where(
            LlmCredential.tenant_id == tenant_id,
            LlmCredential.provider == provider,
        )
    )
    if row is None:
        row = LlmCredential(tenant_id=tenant_id, provider=provider)
        db.add(row)
    if base_url:
        row.base_url = base_url
    if default_model:
        row.default_model = default_model
    if clear_key:
        row.api_key_sealed = ""
        row.key_prefix = ""
    elif api_key:
        row.api_key_sealed = seal_secret(api_key, secret=_secret())
        row.key_prefix = api_key[:4] + "…" if len(api_key) > 4 else "••••"
    row.updated_at = datetime.now(UTC)
    db.flush()
    return row


def resolve_connection(
    db: Session,
    *,
    tenant_id: str,
    provider: str,
    model: str,
) -> tuple[str, str, str, str]:
    """Return provider, model, api_key, base_url (env fills gaps)."""
    settings = get_settings()
    normalized = provider
    if provider in {"local-private", "local"}:
        return "local", model or "local-extractive", "", ""
    if provider in {"openai", "openai_compatible"}:
        normalized = "openai_compatible"
    row = db.scalar(
        select(LlmCredential).where(
            LlmCredential.tenant_id == tenant_id,
            LlmCredential.provider == normalized,
        )
    )
    api_key = ""
    base_url = ""
    resolved_model = model
    if row:
        base_url = row.base_url or ""
        if row.default_model and not model:
            resolved_model = row.default_model
        if row.api_key_sealed:
            try:
                api_key = unseal_secret(row.api_key_sealed, secret=_secret())
            except Exception:  # noqa: BLE001
                api_key = ""
    if normalized == "openai_compatible":
        api_key = api_key or settings.llm_api_key
        base_url = base_url or settings.llm_base_url
        resolved_model = resolved_model or settings.llm_model
    elif normalized == "ollama":
        base_url = base_url or settings.ollama_base_url
        resolved_model = resolved_model or settings.ollama_model
    return normalized, resolved_model, api_key, base_url
