from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from shared.db import get_db
from shared.db.models import AuditEvent, EntityAlias, GraphExtractJob
from shared.errors import AppError, ErrorCode
from shared.graph import (
    entity_mentions_for_user,
    get_entity,
    graph_stats,
    list_entities,
    list_relations,
    neighbors,
    start_extract_job,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import AuthContext, get_current_auth

router = APIRouter(prefix="/v1/graph", tags=["graph"])


class ExtractRequest(BaseModel):
    document_id: str = Field(min_length=1)
    force: bool = False


class JobOut(BaseModel):
    id: str
    document_id: str
    status: str
    chunks_total: int
    chunks_done: int
    entities_created: int
    relations_created: int
    error: str
    trigger: str


class EntityOut(BaseModel):
    id: str
    type: str
    name: str
    canonical_name: str
    mention_count: int
    description: str = ""


class MentionOut(BaseModel):
    id: str
    document_id: str
    chunk_id: str
    mention_text: str
    confidence: float


class EntityDetailOut(EntityOut):
    aliases: list[str]
    mentions: list[MentionOut]


class RelationOut(BaseModel):
    id: str
    subject_entity_id: str
    predicate: str
    object_entity_id: str
    confidence: float
    evidence_document_id: str | None
    evidence_chunk_id: str | None


class NeighborsOut(BaseModel):
    center: EntityOut
    nodes: list[EntityOut]
    edges: list[RelationOut]


class StatsOut(BaseModel):
    entities: int
    relations: int
    documents_covered: int


def _job_out(job: GraphExtractJob) -> JobOut:
    return JobOut(
        id=job.id,
        document_id=job.document_id,
        status=job.status,
        chunks_total=job.chunks_total,
        chunks_done=job.chunks_done,
        entities_created=job.entities_created,
        relations_created=job.relations_created,
        error=job.error or "",
        trigger=job.trigger,
    )


def _entity_out(e) -> EntityOut:
    return EntityOut(
        id=e.id,
        type=e.type,
        name=e.name,
        canonical_name=e.canonical_name,
        mention_count=e.mention_count,
        description=e.description or "",
    )


@router.post("/extract", response_model=JobOut)
def extract(
    body: ExtractRequest,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> JobOut:
    job = start_extract_job(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        document_id=body.document_id,
        force=body.force,
        trigger="manual",
    )
    return _job_out(job)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(
    job_id: str,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> JobOut:
    job = db.get(GraphExtractJob, job_id)
    if job is None or job.tenant_id != auth.tenant_id:
        raise AppError(ErrorCode.NOT_FOUND, "job not found", status_code=404)
    return _job_out(job)


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(
    document_id: str | None = None,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> list[JobOut]:
    stmt = select(GraphExtractJob).where(GraphExtractJob.tenant_id == auth.tenant_id)
    if document_id:
        stmt = stmt.where(GraphExtractJob.document_id == document_id)
    stmt = stmt.order_by(GraphExtractJob.created_at.desc()).limit(20)
    return [_job_out(j) for j in db.scalars(stmt).all()]


@router.get("/entities", response_model=list[EntityOut])
def entities(
    q: str | None = None,
    type: str | None = Query(default=None, alias="type"),
    limit: int = Query(default=50, ge=1, le=100),
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> list[EntityOut]:
    rows = list_entities(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        q=q,
        entity_type=type,
        limit=limit,
    )
    return [_entity_out(e) for e in rows]


@router.get("/entities/{entity_id}", response_model=EntityDetailOut)
def entity_detail(
    entity_id: str,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> EntityDetailOut:
    ent = get_entity(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, entity_id=entity_id
    )
    if ent is None:
        raise AppError(ErrorCode.NOT_FOUND, "entity not found", status_code=404)
    aliases = [
        a.alias
        for a in db.scalars(
            select(EntityAlias).where(
                EntityAlias.tenant_id == auth.tenant_id,
                EntityAlias.entity_id == entity_id,
            )
        ).all()
    ]
    mentions = entity_mentions_for_user(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_id=entity_id,
    )
    db.add(
        AuditEvent(
            tenant_id=auth.tenant_id,
            actor_id=auth.user_id,
            action="graph.entity.viewed",
            resource_type="entity",
            resource_id=entity_id,
            detail=json.dumps({"name": ent.name}),
        )
    )
    return EntityDetailOut(
        **_entity_out(ent).model_dump(),
        aliases=aliases,
        mentions=[
            MentionOut(
                id=m.id,
                document_id=m.document_id,
                chunk_id=m.chunk_id,
                mention_text=m.mention_text,
                confidence=m.confidence,
            )
            for m in mentions
        ],
    )


@router.get("/entities/{entity_id}/neighbors", response_model=NeighborsOut)
def entity_neighbors(
    entity_id: str,
    depth: int = Query(default=1, ge=1, le=2),
    limit: int = Query(default=50, ge=1, le=100),
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> NeighborsOut:
    ng = neighbors(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_id=entity_id,
        depth=depth,
        limit=limit,
    )
    if ng is None:
        raise AppError(ErrorCode.NOT_FOUND, "entity not found", status_code=404)
    return NeighborsOut(
        center=_entity_out(ng.center),
        nodes=[_entity_out(n) for n in ng.nodes],
        edges=[
            RelationOut(
                id=e.id,
                subject_entity_id=e.subject_entity_id,
                predicate=e.predicate,
                object_entity_id=e.object_entity_id,
                confidence=e.confidence,
                evidence_document_id=e.evidence_document_id,
                evidence_chunk_id=e.evidence_chunk_id,
            )
            for e in ng.edges
        ],
    )


@router.get("/relations", response_model=list[RelationOut])
def relations(
    subject_id: str | None = None,
    object_id: str | None = None,
    predicate: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> list[RelationOut]:
    rows = list_relations(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        subject_id=subject_id,
        object_id=object_id,
        predicate=predicate,
        limit=limit,
    )
    return [
        RelationOut(
            id=r.id,
            subject_entity_id=r.subject_entity_id,
            predicate=r.predicate,
            object_entity_id=r.object_entity_id,
            confidence=r.confidence,
            evidence_document_id=r.evidence_document_id,
            evidence_chunk_id=r.evidence_chunk_id,
        )
        for r in rows
    ]


@router.get("/stats", response_model=StatsOut)
def stats(
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> StatsOut:
    return StatsOut(**graph_stats(db, tenant_id=auth.tenant_id, user_id=auth.user_id))
