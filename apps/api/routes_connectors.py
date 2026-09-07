from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.auth import AuthContext, get_current_auth, require_admin
from shared.connectors import create_connector, list_connectors, sync_connector
from shared.db import get_db

router = APIRouter(prefix="/v1", tags=["connectors"])


class ConnectorCreate(BaseModel):
    workspace_id: str
    type: str = Field(default="s3", pattern=r"^[a-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=200)
    config: dict = Field(default_factory=dict)


class ConnectorOut(BaseModel):
    id: str
    workspace_id: str
    type: str
    name: str
    status: str
    config: dict
    permission_mode: str


class SyncRunOut(BaseModel):
    id: str
    connector_id: str
    status: str
    items_seen: int
    items_imported: int
    error_message: str
    detail: dict


def _connector_out(row) -> ConnectorOut:
    return ConnectorOut(
        id=row.id,
        workspace_id=row.workspace_id,
        type=row.type,
        name=row.name,
        status=row.status,
        config=json.loads(row.config_json or "{}"),
        permission_mode=row.permission_mode,
    )


@router.get("/connectors", response_model=list[ConnectorOut])
def get_connectors(
    workspace_id: str | None = Query(default=None),
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> list[ConnectorOut]:
    rows = list_connectors(db, tenant_id=auth.tenant_id, workspace_id=workspace_id)
    return [_connector_out(r) for r in rows]


@router.post("/connectors", response_model=ConnectorOut)
def post_connector(
    body: ConnectorCreate,
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ConnectorOut:
    row = create_connector(
        db,
        tenant_id=auth.tenant_id,
        workspace_id=body.workspace_id,
        user_id=auth.user_id,
        type=body.type,
        name=body.name,
        config=body.config,
    )
    return _connector_out(row)


@router.post("/connectors/{connector_id}/sync", response_model=SyncRunOut)
def post_sync(
    connector_id: str,
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SyncRunOut:
    run = sync_connector(
        db,
        tenant_id=auth.tenant_id,
        connector_id=connector_id,
        user_id=auth.user_id,
    )
    return SyncRunOut(
        id=run.id,
        connector_id=run.connector_id,
        status=run.status,
        items_seen=run.items_seen,
        items_imported=run.items_imported,
        error_message=run.error_message,
        detail=json.loads(run.detail_json or "{}"),
    )
