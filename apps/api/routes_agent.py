from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.auth import AuthContext, get_current_auth
from shared.agent import ALL_TOOLS, DEFAULT_ALLOWLIST, get_agent_run, list_tool_calls, run_agent
from shared.db import get_db
from shared.db.models import Workspace
from shared.errors import AppError, ErrorCode
from sqlalchemy import select

router = APIRouter(prefix="/v1", tags=["agent"])


class AgentRunRequest(BaseModel):
    workspace_id: str
    goal: str = Field(min_length=1, max_length=2000)
    tool_allowlist: list[str] | None = None
    dry_run: bool = False
    max_steps: int = Field(default=8, ge=1, le=16)


class ToolCallOut(BaseModel):
    id: str
    tool_name: str
    status: str
    input: dict
    output: dict


class AgentRunOut(BaseModel):
    id: str
    workspace_id: str
    goal: str
    status: str
    dry_run: bool
    allowlist: list[str]
    answer: str
    tool_calls: list[ToolCallOut]


class ToolsCatalogOut(BaseModel):
    tools: list[str]
    default_allowlist: list[str]
    dangerous: list[str]


@router.get("/agent/tools", response_model=ToolsCatalogOut)
def tools_catalog(_: AuthContext = Depends(get_current_auth)) -> ToolsCatalogOut:
    from shared.agent import DANGEROUS_TOOLS

    return ToolsCatalogOut(
        tools=sorted(ALL_TOOLS),
        default_allowlist=DEFAULT_ALLOWLIST,
        dangerous=sorted(DANGEROUS_TOOLS),
    )


@router.post("/agent/runs", response_model=AgentRunOut)
def create_agent_run(
    body: AgentRunRequest,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> AgentRunOut:
    ws = db.scalar(
        select(Workspace).where(
            Workspace.id == body.workspace_id,
            Workspace.tenant_id == auth.tenant_id,
            Workspace.status == "active",
        )
    )
    if ws is None:
        raise AppError(ErrorCode.NOT_FOUND, "workspace not found", status_code=404)

    run = run_agent(
        db,
        tenant_id=auth.tenant_id,
        workspace_id=body.workspace_id,
        user_id=auth.user_id,
        role=auth.role,
        goal=body.goal,
        tool_allowlist=body.tool_allowlist,
        dry_run=body.dry_run,
        max_steps=body.max_steps,
    )
    calls = list_tool_calls(db, tenant_id=auth.tenant_id, run_id=run.id)
    return AgentRunOut(
        id=run.id,
        workspace_id=run.workspace_id,
        goal=run.goal,
        status=run.status,
        dry_run=bool(run.dry_run),
        allowlist=json.loads(run.allowlist_json or "[]"),
        answer=run.answer,
        tool_calls=[
            ToolCallOut(
                id=c.id,
                tool_name=c.tool_name,
                status=c.status,
                input=json.loads(c.input_json or "{}"),
                output=json.loads(c.output_json or "{}"),
            )
            for c in calls
        ],
    )


@router.get("/agent/runs/{run_id}", response_model=AgentRunOut)
def get_run(
    run_id: str,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> AgentRunOut:
    run = get_agent_run(db, tenant_id=auth.tenant_id, run_id=run_id)
    if run is None:
        raise AppError(ErrorCode.NOT_FOUND, "agent run not found", status_code=404)
    calls = list_tool_calls(db, tenant_id=auth.tenant_id, run_id=run.id)
    return AgentRunOut(
        id=run.id,
        workspace_id=run.workspace_id,
        goal=run.goal,
        status=run.status,
        dry_run=bool(run.dry_run),
        allowlist=json.loads(run.allowlist_json or "[]"),
        answer=run.answer,
        tool_calls=[
            ToolCallOut(
                id=c.id,
                tool_name=c.tool_name,
                status=c.status,
                input=json.loads(c.input_json or "{}"),
                output=json.loads(c.output_json or "{}"),
            )
            for c in calls
        ],
    )
