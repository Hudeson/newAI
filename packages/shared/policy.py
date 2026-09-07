from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.db.models import ModelRoutePolicy

DEFAULT_ROUTES: dict[str, tuple[str, str]] = {
    "L1": ("local", "local-extractive"),
    "L2": ("local", "local-extractive"),
    "L3": ("local-private", "local-private-extractive"),
    "L4": ("local-private", "local-private-extractive"),
}

VALID_SENSITIVITY = set(DEFAULT_ROUTES)


def ensure_default_policies(db: Session, *, tenant_id: str) -> list[ModelRoutePolicy]:
    existing = {
        p.sensitivity: p
        for p in db.scalars(
            select(ModelRoutePolicy).where(ModelRoutePolicy.tenant_id == tenant_id)
        ).all()
    }
    rows: list[ModelRoutePolicy] = []
    for sensitivity, (provider, model) in DEFAULT_ROUTES.items():
        if sensitivity in existing:
            rows.append(existing[sensitivity])
            continue
        row = ModelRoutePolicy(
            tenant_id=tenant_id,
            sensitivity=sensitivity,
            provider=provider,
            model=model,
        )
        db.add(row)
        rows.append(row)
    db.flush()
    return rows


def list_policies(db: Session, *, tenant_id: str) -> list[ModelRoutePolicy]:
    ensure_default_policies(db, tenant_id=tenant_id)
    return list(
        db.scalars(
            select(ModelRoutePolicy)
            .where(ModelRoutePolicy.tenant_id == tenant_id)
            .order_by(ModelRoutePolicy.sensitivity.asc())
        ).all()
    )


def upsert_policy(
    db: Session,
    *,
    tenant_id: str,
    sensitivity: str,
    provider: str,
    model: str,
) -> ModelRoutePolicy:
    if sensitivity not in VALID_SENSITIVITY:
        raise ValueError(f"invalid sensitivity: {sensitivity}")
    ensure_default_policies(db, tenant_id=tenant_id)
    row = db.scalar(
        select(ModelRoutePolicy).where(
            ModelRoutePolicy.tenant_id == tenant_id,
            ModelRoutePolicy.sensitivity == sensitivity,
        )
    )
    assert row is not None
    row.provider = provider
    row.model = model
    row.updated_at = datetime.now(UTC)
    db.flush()
    return row


def resolve_route(db: Session, *, tenant_id: str, sensitivity: str) -> tuple[str, str]:
    level = sensitivity if sensitivity in VALID_SENSITIVITY else "L2"
    ensure_default_policies(db, tenant_id=tenant_id)
    row = db.scalar(
        select(ModelRoutePolicy).where(
            ModelRoutePolicy.tenant_id == tenant_id,
            ModelRoutePolicy.sensitivity == level,
        )
    )
    if row is None:
        return DEFAULT_ROUTES[level]
    return row.provider, row.model
