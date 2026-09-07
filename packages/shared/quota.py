from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shared.db.models import DocumentVersion, TenantQuota, UsageLedger
from shared.errors import AppError, ErrorCode

DEFAULT_QUOTAS: dict[str, tuple[int, str]] = {
    "ask": (200, "day"),
    "learn": (100, "day"),
    "search": (1000, "day"),
    "agent": (50, "day"),
    "llm_tokens": (200_000, "day"),
    "upload_bytes": (500_000_000, "lifetime"),
}

OPERATION_METERS = {
    "ask": "ask",
    "learn": "learn",
    "search": "search",
    "agent": "agent",
}


def ensure_default_quotas(db: Session, *, tenant_id: str) -> list[TenantQuota]:
    existing = {
        q.meter: q
        for q in db.scalars(select(TenantQuota).where(TenantQuota.tenant_id == tenant_id)).all()
    }
    rows: list[TenantQuota] = []
    for meter, (limit_value, window) in DEFAULT_QUOTAS.items():
        if meter in existing:
            rows.append(existing[meter])
            continue
        row = TenantQuota(
            tenant_id=tenant_id,
            meter=meter,
            limit_value=limit_value,
            window=window,
        )
        db.add(row)
        rows.append(row)
    db.flush()
    return rows


def list_quotas(db: Session, *, tenant_id: str) -> list[TenantQuota]:
    ensure_default_quotas(db, tenant_id=tenant_id)
    return list(db.scalars(select(TenantQuota).where(TenantQuota.tenant_id == tenant_id)).all())


def set_quota(
    db: Session,
    *,
    tenant_id: str,
    meter: str,
    limit_value: int,
    window: str | None = None,
) -> TenantQuota:
    ensure_default_quotas(db, tenant_id=tenant_id)
    row = db.scalar(
        select(TenantQuota).where(TenantQuota.tenant_id == tenant_id, TenantQuota.meter == meter)
    )
    if row is None:
        row = TenantQuota(
            tenant_id=tenant_id,
            meter=meter,
            limit_value=limit_value,
            window=window or DEFAULT_QUOTAS.get(meter, (0, "day"))[1],
        )
        db.add(row)
    else:
        row.limit_value = limit_value
        if window:
            row.window = window
        row.updated_at = datetime.now(UTC)
    db.flush()
    return row


def _day_start() -> datetime:
    now = datetime.now(UTC)
    return datetime(now.year, now.month, now.day, tzinfo=UTC)


def usage_count(
    db: Session,
    *,
    tenant_id: str,
    operation: str,
    window: str,
) -> int:
    stmt = select(func.count()).select_from(UsageLedger).where(
        UsageLedger.tenant_id == tenant_id,
        UsageLedger.operation == operation,
    )
    if window == "day":
        stmt = stmt.where(UsageLedger.created_at >= _day_start())
    return int(db.scalar(stmt) or 0)


def token_usage(db: Session, *, tenant_id: str, window: str) -> int:
    stmt = select(
        func.coalesce(func.sum(UsageLedger.input_tokens + UsageLedger.output_tokens), 0)
    ).where(UsageLedger.tenant_id == tenant_id)
    if window == "day":
        stmt = stmt.where(UsageLedger.created_at >= _day_start())
    return int(db.scalar(stmt) or 0)


def upload_bytes_used(db: Session, *, tenant_id: str) -> int:
    total = db.scalar(
        select(func.coalesce(func.sum(DocumentVersion.size_bytes), 0)).where(
            DocumentVersion.tenant_id == tenant_id
        )
    )
    return int(total or 0)


def meter_usage(db: Session, *, tenant_id: str, meter: str, window: str) -> int:
    if meter == "llm_tokens":
        return token_usage(db, tenant_id=tenant_id, window=window)
    if meter == "upload_bytes":
        return upload_bytes_used(db, tenant_id=tenant_id)
    return usage_count(db, tenant_id=tenant_id, operation=meter, window=window)


def usage_summary(db: Session, *, tenant_id: str) -> list[dict]:
    rows = []
    for q in list_quotas(db, tenant_id=tenant_id):
        used = meter_usage(db, tenant_id=tenant_id, meter=q.meter, window=q.window)
        rows.append(
            {
                "meter": q.meter,
                "limit": q.limit_value,
                "used": used,
                "remaining": max(q.limit_value - used, 0),
                "window": q.window,
            }
        )
    return rows


def enforce_quota(
    db: Session,
    *,
    tenant_id: str,
    meter: str,
    amount: int = 1,
) -> None:
    ensure_default_quotas(db, tenant_id=tenant_id)
    row = db.scalar(
        select(TenantQuota).where(TenantQuota.tenant_id == tenant_id, TenantQuota.meter == meter)
    )
    if row is None:
        return
    used = meter_usage(db, tenant_id=tenant_id, meter=meter, window=row.window)
    if used + amount > row.limit_value:
        raise AppError(
            ErrorCode.QUOTA_EXCEEDED,
            f"quota exceeded for meter={meter}",
            status_code=429,
            details={
                "meter": meter,
                "limit": row.limit_value,
                "used": used,
                "requested": amount,
                "window": row.window,
            },
        )


def enforce_operation_quota(db: Session, *, tenant_id: str, operation: str) -> None:
    meter = OPERATION_METERS.get(operation, operation)
    enforce_quota(db, tenant_id=tenant_id, meter=meter, amount=1)
