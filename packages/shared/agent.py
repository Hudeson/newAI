from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.acl import can_read_document
from shared.db.models import AgentRun, AgentToolCall, AuditEvent, LearningReport
from shared.errors import AppError, ErrorCode
from shared.llm import record_usage
from shared.quota import enforce_operation_quota
from shared.search import search_chunks

SAFE_TOOLS = {
    "search_knowledge",
    "get_learning",
    "review_summarize",
}
DANGEROUS_TOOLS = {
    "manage_acl",
    "export_audit",
}
ALL_TOOLS = SAFE_TOOLS | DANGEROUS_TOOLS
DEFAULT_ALLOWLIST = sorted(SAFE_TOOLS)


@dataclass
class ToolResult:
    tool_name: str
    status: str
    input: dict
    output: dict


def validate_allowlist(tools: list[str], *, role: str) -> list[str]:
    cleaned: list[str] = []
    for name in tools:
        if name not in ALL_TOOLS:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                f"unknown tool: {name}",
                status_code=400,
                details={"tool": name, "allowed": sorted(ALL_TOOLS)},
            )
        if name in DANGEROUS_TOOLS and role not in {"admin", "owner"}:
            raise AppError(
                ErrorCode.FORBIDDEN,
                f"tool requires admin: {name}",
                status_code=403,
                details={"tool": name},
            )
        cleaned.append(name)
    if not cleaned:
        raise AppError(ErrorCode.VALIDATION_ERROR, "tool_allowlist empty", status_code=400)
    return cleaned


def _call_search(db: Session, *, tenant_id: str, user_id: str, goal: str, dry_run: bool) -> dict:
    if dry_run:
        return {"planned": True, "query": goal, "hit_count": 0}
    hits = search_chunks(db, tenant_id=tenant_id, user_id=user_id, query=goal, limit=5)
    return {
        "query": goal,
        "hit_count": len(hits),
        "document_ids": list({h.document_id for h in hits}),
        "snippets": [h.content[:160] for h in hits[:3]],
    }


def _call_learning(db: Session, *, tenant_id: str, user_id: str, document_ids: list[str], dry_run: bool) -> dict:
    if dry_run:
        return {"planned": True, "document_ids": document_ids[:1]}
    if not document_ids:
        return {"found": False}
    doc_id = document_ids[0]
    if not can_read_document(db, tenant_id=tenant_id, user_id=user_id, document_id=doc_id):
        return {"found": False, "reason": "acl_denied"}
    report = db.scalar(
        select(LearningReport)
        .where(LearningReport.tenant_id == tenant_id, LearningReport.document_id == doc_id)
        .order_by(LearningReport.created_at.desc())
    )
    if report is None:
        return {"found": False}
    return {
        "found": True,
        "document_id": doc_id,
        "status": report.status,
        "summary": report.summary[:500],
    }


def _call_review(db: Session, *, tenant_id: str, goal: str, snippets: list[str], dry_run: bool) -> dict:
    if dry_run:
        return {"planned": True, "goal": goal}
    joined = " ".join(snippets)[:800] or goal
    return {
        "review": f"Review of '{goal}': {joined[:400]}",
        "length": len(joined),
    }


def run_agent(
    db: Session,
    *,
    tenant_id: str,
    workspace_id: str,
    user_id: str,
    role: str,
    goal: str,
    tool_allowlist: list[str] | None = None,
    dry_run: bool = False,
    max_steps: int = 8,
) -> AgentRun:
    enforce_operation_quota(db, tenant_id=tenant_id, operation="agent")
    allowlist = validate_allowlist(tool_allowlist or DEFAULT_ALLOWLIST, role=role)
    allowlist = allowlist[:max_steps]

    run = AgentRun(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        user_id=user_id,
        goal=goal,
        status="running",
        dry_run=1 if dry_run else 0,
        allowlist_json=json.dumps(allowlist),
    )
    db.add(run)
    db.flush()

    results: list[ToolResult] = []
    doc_ids: list[str] = []
    snippets: list[str] = []

    for tool in allowlist:
        if tool not in allowlist:
            continue
        if tool == "search_knowledge":
            out = _call_search(db, tenant_id=tenant_id, user_id=user_id, goal=goal, dry_run=dry_run)
            doc_ids = list(out.get("document_ids") or doc_ids)
            snippets = list(out.get("snippets") or snippets)
            status = "dry_run" if dry_run else "ok"
            inp = {"query": goal}
        elif tool == "get_learning":
            out = _call_learning(
                db, tenant_id=tenant_id, user_id=user_id, document_ids=doc_ids, dry_run=dry_run
            )
            status = "dry_run" if dry_run else "ok"
            inp = {"document_ids": doc_ids[:3]}
        elif tool == "review_summarize":
            out = _call_review(db, tenant_id=tenant_id, goal=goal, snippets=snippets, dry_run=dry_run)
            status = "dry_run" if dry_run else "ok"
            inp = {"goal": goal}
        elif tool in DANGEROUS_TOOLS:
            # Still require explicit allowlist + admin; dry-run only for safety in E7.
            if not dry_run:
                status = "denied"
                out = {"reason": "dangerous_tool_requires_dry_run_in_e7"}
            else:
                status = "dry_run"
                out = {"planned": True, "tool": tool}
            inp = {"tool": tool}
        else:
            status = "denied"
            out = {"reason": "unsupported"}
            inp = {}

        call = AgentToolCall(
            tenant_id=tenant_id,
            run_id=run.id,
            tool_name=tool,
            status=status,
            input_json=json.dumps(inp),
            output_json=json.dumps(out),
        )
        db.add(call)
        results.append(ToolResult(tool_name=tool, status=status, input=inp, output=out))

    answer_parts = []
    for r in results:
        if r.tool_name == "review_summarize" and r.output.get("review"):
            answer_parts.append(r.output["review"])
        elif r.tool_name == "get_learning" and r.output.get("summary"):
            answer_parts.append(r.output["summary"])
        elif r.tool_name == "search_knowledge" and r.output.get("snippets"):
            answer_parts.append("Sources: " + " | ".join(r.output["snippets"][:2]))
    if dry_run:
        answer = f"[dry-run] Planned tools: {', '.join(allowlist)} for goal: {goal}"
    else:
        answer = "\n\n".join(answer_parts) or f"Completed tools {', '.join(allowlist)} for: {goal}"

    run.answer = answer
    run.status = "completed"
    run.detail_json = json.dumps({"steps": len(results), "tools": [r.tool_name for r in results]})

    record_usage(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        operation="agent",
        provider="local",
        model="agent-tools",
        input_tokens=max(len(goal.split()), 1),
        output_tokens=max(len(answer.split()), 1),
        detail={"run_id": run.id, "dry_run": dry_run},
    )
    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_id=user_id,
            action="agent.run.completed",
            resource_type="agent_run",
            resource_id=run.id,
            detail=json.dumps({"dry_run": dry_run, "tools": allowlist}),
        )
    )
    db.flush()
    return run


def get_agent_run(db: Session, *, tenant_id: str, run_id: str) -> AgentRun | None:
    return db.scalar(
        select(AgentRun).where(AgentRun.id == run_id, AgentRun.tenant_id == tenant_id)
    )


def list_tool_calls(db: Session, *, tenant_id: str, run_id: str) -> list[AgentToolCall]:
    return list(
        db.scalars(
            select(AgentToolCall)
            .where(AgentToolCall.tenant_id == tenant_id, AgentToolCall.run_id == run_id)
            .order_by(AgentToolCall.created_at.asc())
        ).all()
    )
