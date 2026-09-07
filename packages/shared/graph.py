"""Knowledge graph: normalize, extract, ACL-aware query."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from shared.acl import can_read_document, readable_document_ids
from shared.config import get_settings
from shared.db.models import (
    AuditEvent,
    Chunk,
    Document,
    Entity,
    EntityAlias,
    EntityMention,
    GraphExtractJob,
    Relation,
)
from shared.errors import AppError, ErrorCode
from shared.gateway import build_graph_extract_messages
from shared.llm import gateway_complete, record_usage
from shared.logging import get_logger

logger = get_logger("graph")

ENTITY_TYPES = frozenset(
    {
        "person",
        "organization",
        "product",
        "concept",
        "location",
        "event",
        "document_ref",
        "other",
    }
)

PREDICATES = frozenset(
    {
        "related_to",
        "part_of",
        "works_at",
        "authored_by",
        "depends_on",
        "defines",
        "references",
        "located_in",
        "occurs_in",
        "synonym_of",
    }
)

_TITLE_CASE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b")
_BOOK = re.compile(r"《([^》]{2,80})》")
_BELONGS = re.compile(
    r"([A-Za-z\u4e00-\u9fff][\w\u4e00-\u9fff\-]{1,40})\s*(?:属于|隶属于|works at|part of)\s*"
    r"([A-Za-z\u4e00-\u9fff][\w\u4e00-\u9fff\-]{1,40})",
    re.IGNORECASE,
)


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip()).lower()


def name_hash(tenant_id: str, entity_type: str, canonical: str) -> str:
    raw = f"{tenant_id}|{entity_type}|{canonical}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_type(raw: str | None) -> str:
    t = (raw or "other").strip().lower().replace("-", "_").replace(" ", "_")
    return t if t in ENTITY_TYPES else "other"


def normalize_predicate(raw: str | None) -> tuple[str, str | None]:
    p = (raw or "related_to").strip().lower().replace("-", "_").replace(" ", "_")
    if p in PREDICATES:
        return p, None
    return "related_to", raw


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def upsert_entity(
    db: Session,
    *,
    tenant_id: str,
    name: str,
    entity_type: str = "other",
    aliases: list[str] | None = None,
) -> Entity:
    etype = normalize_type(entity_type)
    display = (name or "").strip()
    if not display:
        raise ValueError("empty entity name")
    canonical = normalize_name(display)
    h = name_hash(tenant_id, etype, canonical)
    existing = db.scalar(
        select(Entity).where(Entity.tenant_id == tenant_id, Entity.name_hash == h)
    )
    if existing is None:
        existing = Entity(
            tenant_id=tenant_id,
            type=etype,
            name=display,
            canonical_name=canonical,
            name_hash=h,
        )
        db.add(existing)
        db.flush()
    for alias in aliases or []:
        a = (alias or "").strip()
        if not a:
            continue
        ca = normalize_name(a)
        if ca == canonical:
            continue
        found = db.scalar(
            select(EntityAlias).where(
                EntityAlias.tenant_id == tenant_id,
                EntityAlias.entity_id == existing.id,
                EntityAlias.canonical_alias == ca,
            )
        )
        if found is None:
            db.add(
                EntityAlias(
                    tenant_id=tenant_id,
                    entity_id=existing.id,
                    alias=a,
                    canonical_alias=ca,
                    source="extract",
                )
            )
    db.flush()
    return existing


def add_mention(
    db: Session,
    *,
    tenant_id: str,
    entity: Entity,
    document_id: str,
    chunk_id: str,
    mention_text: str,
    confidence: float = 0.5,
) -> EntityMention:
    mention = EntityMention(
        tenant_id=tenant_id,
        entity_id=entity.id,
        document_id=document_id,
        chunk_id=chunk_id,
        mention_text=mention_text[:500],
        confidence=confidence,
    )
    db.add(mention)
    entity.mention_count = int(entity.mention_count or 0) + 1
    entity.updated_at = _utcnow()
    db.flush()
    return mention


def add_relation(
    db: Session,
    *,
    tenant_id: str,
    subject: Entity,
    predicate: str,
    obj: Entity,
    document_id: str,
    chunk_id: str,
    confidence: float = 0.5,
    raw_predicate: str | None = None,
) -> Relation:
    pred, raw = normalize_predicate(predicate)
    attrs: dict[str, Any] = {}
    if raw_predicate or raw:
        attrs["raw_predicate"] = raw_predicate or raw
    rel = Relation(
        tenant_id=tenant_id,
        subject_entity_id=subject.id,
        predicate=pred,
        object_entity_id=obj.id,
        attributes_json=json.dumps(attrs, ensure_ascii=False),
        evidence_chunk_id=chunk_id,
        evidence_document_id=document_id,
        confidence=confidence,
    )
    db.add(rel)
    db.flush()
    return rel


def clear_document_graph(db: Session, *, tenant_id: str, document_id: str) -> None:
    mentions = db.scalars(
        select(EntityMention).where(
            EntityMention.tenant_id == tenant_id,
            EntityMention.document_id == document_id,
        )
    ).all()
    entity_ids = {m.entity_id for m in mentions}
    for m in mentions:
        db.delete(m)
    rels = db.scalars(
        select(Relation).where(
            Relation.tenant_id == tenant_id,
            Relation.evidence_document_id == document_id,
        )
    ).all()
    for r in rels:
        db.delete(r)
    db.flush()
    for eid in entity_ids:
        ent = db.get(Entity, eid)
        if ent is None or ent.tenant_id != tenant_id:
            continue
        count = db.scalar(
            select(func.count())
            .select_from(EntityMention)
            .where(EntityMention.entity_id == eid)
        )
        ent.mention_count = int(count or 0)
        if ent.mention_count == 0:
            aliases = db.scalars(
                select(EntityAlias).where(EntityAlias.entity_id == eid)
            ).all()
            for a in aliases:
                db.delete(a)
            db.delete(ent)
    db.flush()


def rule_extract(text: str) -> dict[str, Any]:
    """Local fallback: title-case / book titles / simple belonging patterns."""
    entities: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_ent(name: str, etype: str = "other") -> None:
        key = normalize_name(name)
        if len(key) < 2 or key in seen:
            return
        seen.add(key)
        entities.append({"name": name.strip(), "type": etype, "aliases": []})

    for m in _BOOK.finditer(text or ""):
        add_ent(m.group(1), "document_ref")
    for m in _TITLE_CASE.finditer(text or ""):
        add_ent(m.group(1), "concept")
    for m in _BELONGS.finditer(text or ""):
        subj, obj = m.group(1), m.group(2)
        add_ent(subj, "person")
        add_ent(obj, "organization")
        relations.append(
            {
                "subject": subj,
                "predicate": "works_at",
                "object": obj,
                "evidence": m.group(0)[:200],
            }
        )
    # Prefer longer capitalized phrases as products/orgs when many found
    return {"entities": entities[:40], "relations": relations[:40]}


def parse_extract_json(raw: str) -> dict[str, Any] | None:
    cleaned = (raw or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    entities = data.get("entities") or []
    relations = data.get("relations") or []
    if not isinstance(entities, list):
        entities = []
    if not isinstance(relations, list):
        relations = []
    return {"entities": entities, "relations": relations}


def extract_chunk_payload(
    db: Session,
    *,
    tenant_id: str,
    user_id: str | None,
    text: str,
    title: str,
    sensitivity: str,
) -> dict[str, Any]:
    from shared.credentials import resolve_connection
    from shared.policy import resolve_route

    settings = get_settings()
    payload: dict[str, Any] | None = None
    route_provider, route_model = resolve_route(db, tenant_id=tenant_id, sensitivity=sensitivity)
    provider, _model, api_key, _base = resolve_connection(
        db,
        tenant_id=tenant_id,
        provider=route_provider,
        model=route_model,
    )
    use_llm = provider not in {"local", ""} and not (
        provider == "openai_compatible" and not api_key
    )
    if use_llm:
        try:
            raw = gateway_complete(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                prompt=title or "untitled",
                context_blocks=[text],
                operation="graph_extract",
                sensitivity=sensitivity,
                purpose="graph_extract",
            )
            payload = parse_extract_json(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("graph_extract_llm_failed", error=str(exc)[:300])
            payload = None
    if settings.graph_local_fallback and (
        not payload or (not payload.get("entities") and not payload.get("relations"))
    ):
        payload = rule_extract(text)
        record_usage(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            operation="graph_extract",
            provider="local",
            model="rule-extract",
            detail={"fallback": True, "title": (title or "")[:120]},
        )
    return payload or {"entities": [], "relations": []}


def apply_payload(
    db: Session,
    *,
    tenant_id: str,
    document_id: str,
    chunk_id: str,
    payload: dict[str, Any],
    confidence: float = 0.55,
) -> tuple[int, int]:
    name_to_entity: dict[str, Entity] = {}
    entities_n = 0
    relations_n = 0
    for item in payload.get("entities") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        aliases = [str(a) for a in (item.get("aliases") or []) if str(a).strip()]
        ent = upsert_entity(
            db,
            tenant_id=tenant_id,
            name=name,
            entity_type=str(item.get("type") or "other"),
            aliases=aliases,
        )
        add_mention(
            db,
            tenant_id=tenant_id,
            entity=ent,
            document_id=document_id,
            chunk_id=chunk_id,
            mention_text=name,
            confidence=confidence,
        )
        name_to_entity[normalize_name(name)] = ent
        entities_n += 1
    for item in payload.get("relations") or []:
        if not isinstance(item, dict):
            continue
        subj_name = str(item.get("subject") or "").strip()
        obj_name = str(item.get("object") or "").strip()
        if not subj_name or not obj_name:
            continue
        subj = name_to_entity.get(normalize_name(subj_name))
        obj = name_to_entity.get(normalize_name(obj_name))
        if subj is None:
            subj = upsert_entity(db, tenant_id=tenant_id, name=subj_name)
            add_mention(
                db,
                tenant_id=tenant_id,
                entity=subj,
                document_id=document_id,
                chunk_id=chunk_id,
                mention_text=subj_name,
                confidence=confidence * 0.9,
            )
            name_to_entity[normalize_name(subj_name)] = subj
            entities_n += 1
        if obj is None:
            obj = upsert_entity(db, tenant_id=tenant_id, name=obj_name)
            add_mention(
                db,
                tenant_id=tenant_id,
                entity=obj,
                document_id=document_id,
                chunk_id=chunk_id,
                mention_text=obj_name,
                confidence=confidence * 0.9,
            )
            name_to_entity[normalize_name(obj_name)] = obj
            entities_n += 1
        add_relation(
            db,
            tenant_id=tenant_id,
            subject=subj,
            predicate=str(item.get("predicate") or "related_to"),
            obj=obj,
            document_id=document_id,
            chunk_id=chunk_id,
            confidence=confidence,
            raw_predicate=str(item.get("predicate") or ""),
        )
        relations_n += 1
    return entities_n, relations_n


def start_extract_job(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    document_id: str,
    force: bool = False,
    trigger: str = "manual",
) -> GraphExtractJob:
    doc = db.get(Document, document_id)
    if doc is None or doc.tenant_id != tenant_id:
        raise AppError(ErrorCode.NOT_FOUND, "document not found", status_code=404)
    if not can_read_document(db, tenant_id=tenant_id, user_id=user_id, document_id=document_id):
        raise AppError(ErrorCode.FORBIDDEN, "document not readable", status_code=403)
    active = db.scalars(
        select(GraphExtractJob).where(
            GraphExtractJob.tenant_id == tenant_id,
            GraphExtractJob.document_id == document_id,
            GraphExtractJob.status.in_(("queued", "running")),
        )
    ).first()
    if active is not None:
        raise AppError(
            ErrorCode.CONFLICT,
            "extract job already running",
            status_code=409,
            details={"job_id": active.id},
        )

    settings = get_settings()
    day_start = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = db.scalar(
        select(func.count())
        .select_from(GraphExtractJob)
        .where(
            GraphExtractJob.tenant_id == tenant_id,
            GraphExtractJob.created_at >= day_start,
            GraphExtractJob.status.in_(("queued", "running", "succeeded")),
        )
    )
    if int(today_count or 0) >= settings.graph_extract_max_docs_per_day:
        raise AppError(ErrorCode.QUOTA_EXCEEDED, "graph extract daily quota exceeded", status_code=429)

    chunks = db.scalars(
        select(Chunk)
        .where(
            Chunk.tenant_id == tenant_id,
            Chunk.document_id == document_id,
            Chunk.status == "active",
        )
        .order_by(Chunk.ordinal.asc())
    ).all()
    if not chunks:
        raise AppError(ErrorCode.VALIDATION_ERROR, "document has no chunks", status_code=400)

    max_chunks = settings.graph_extract_max_chunks_per_doc
    chunks = list(chunks)[:max_chunks]

    if force:
        clear_document_graph(db, tenant_id=tenant_id, document_id=document_id)

    job = GraphExtractJob(
        tenant_id=tenant_id,
        document_id=document_id,
        status="queued",
        chunks_total=len(chunks),
        trigger=trigger,
    )
    db.add(job)
    db.flush()
    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_id=user_id,
            action="graph.extract.started",
            resource_type="document",
            resource_id=document_id,
            detail=json.dumps({"job_id": job.id, "force": force, "chunks": len(chunks)}),
        )
    )
    db.flush()

    # Personal path: run inline (same as ingest).
    run_extract_job(db, job=job, user_id=user_id, chunks=chunks, document=doc)
    return job


def run_extract_job(
    db: Session,
    *,
    job: GraphExtractJob,
    user_id: str,
    chunks: list[Chunk],
    document: Document,
) -> None:
    job.status = "running"
    job.updated_at = _utcnow()
    db.flush()
    entities_created = 0
    relations_created = 0
    try:
        for chunk in chunks:
            payload = extract_chunk_payload(
                db,
                tenant_id=job.tenant_id,
                user_id=user_id,
                text=chunk.content or "",
                title=document.title or "",
                sensitivity=document.sensitivity or "L2",
            )
            # Rule fallback confidence lower; LLM path slightly higher if entities present
            conf = 0.45 if payload.get("_rule") else 0.65
            # Detect rule-only via empty LLM: rule_extract has no marker — use presence of title-case
            e_n, r_n = apply_payload(
                db,
                tenant_id=job.tenant_id,
                document_id=job.document_id,
                chunk_id=chunk.id,
                payload=payload,
                confidence=conf,
            )
            entities_created += e_n
            relations_created += r_n
            job.chunks_done = int(job.chunks_done or 0) + 1
            job.entities_created = entities_created
            job.relations_created = relations_created
            job.updated_at = _utcnow()
            db.flush()
        job.status = "succeeded"
        job.finished_at = _utcnow()
        job.updated_at = job.finished_at
        db.add(
            AuditEvent(
                tenant_id=job.tenant_id,
                actor_id=user_id,
                action="graph.extract.succeeded",
                resource_type="graph_extract_job",
                resource_id=job.id,
                detail=json.dumps(
                    {
                        "entities": entities_created,
                        "relations": relations_created,
                        "chunks": job.chunks_done,
                    }
                ),
            )
        )
        db.flush()
    except Exception as exc:  # noqa: BLE001
        logger.exception("graph_extract_failed", job_id=job.id)
        job.status = "failed"
        job.error = str(exc)[:1000]
        job.finished_at = _utcnow()
        job.updated_at = job.finished_at
        db.add(
            AuditEvent(
                tenant_id=job.tenant_id,
                actor_id=user_id,
                action="graph.extract.failed",
                resource_type="graph_extract_job",
                resource_id=job.id,
                detail=json.dumps({"error": job.error[:300]}),
            )
        )
        db.flush()


def visible_entity_ids(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
) -> set[str]:
    allowed_docs = readable_document_ids(db, tenant_id=tenant_id, user_id=user_id)
    if not allowed_docs:
        return set()
    rows = db.scalars(
        select(EntityMention.entity_id).where(
            EntityMention.tenant_id == tenant_id,
            EntityMention.document_id.in_(allowed_docs),
        )
    ).all()
    return set(rows)


def list_entities(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    q: str | None = None,
    entity_type: str | None = None,
    limit: int = 50,
) -> list[Entity]:
    visible = visible_entity_ids(db, tenant_id=tenant_id, user_id=user_id)
    if not visible:
        return []
    stmt = select(Entity).where(Entity.tenant_id == tenant_id, Entity.id.in_(visible))
    if entity_type:
        stmt = stmt.where(Entity.type == normalize_type(entity_type))
    if q:
        like = f"%{normalize_name(q)}%"
        stmt = stmt.where(
            or_(
                Entity.canonical_name.like(like),
                Entity.name.ilike(f"%{q.strip()}%"),
            )
        )
    stmt = stmt.order_by(Entity.mention_count.desc(), Entity.name.asc()).limit(min(limit, 100))
    return list(db.scalars(stmt).all())


def get_entity(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    entity_id: str,
) -> Entity | None:
    visible = visible_entity_ids(db, tenant_id=tenant_id, user_id=user_id)
    if entity_id not in visible:
        return None
    ent = db.get(Entity, entity_id)
    if ent is None or ent.tenant_id != tenant_id:
        return None
    return ent


def entity_mentions_for_user(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    entity_id: str,
    limit: int = 20,
) -> list[EntityMention]:
    allowed = readable_document_ids(db, tenant_id=tenant_id, user_id=user_id)
    if not allowed:
        return []
    return list(
        db.scalars(
            select(EntityMention)
            .where(
                EntityMention.tenant_id == tenant_id,
                EntityMention.entity_id == entity_id,
                EntityMention.document_id.in_(allowed),
            )
            .order_by(EntityMention.created_at.desc())
            .limit(limit)
        ).all()
    )


@dataclass
class NeighborGraph:
    center: Entity
    nodes: list[Entity]
    edges: list[Relation]


def neighbors(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    entity_id: str,
    depth: int = 1,
    limit: int = 50,
) -> NeighborGraph | None:
    settings = get_settings()
    depth = max(1, min(depth, settings.graph_neighbor_max_depth))
    center = get_entity(db, tenant_id=tenant_id, user_id=user_id, entity_id=entity_id)
    if center is None:
        return None
    visible = visible_entity_ids(db, tenant_id=tenant_id, user_id=user_id)
    allowed_docs = readable_document_ids(db, tenant_id=tenant_id, user_id=user_id)
    frontier = {entity_id}
    seen_nodes = {entity_id}
    edge_ids: set[str] = set()
    edges: list[Relation] = []
    for _ in range(depth):
        if not frontier:
            break
        rels = db.scalars(
            select(Relation).where(
                Relation.tenant_id == tenant_id,
                or_(
                    Relation.subject_entity_id.in_(frontier),
                    Relation.object_entity_id.in_(frontier),
                ),
            )
        ).all()
        next_frontier: set[str] = set()
        for r in rels:
            if r.id in edge_ids:
                continue
            if r.subject_entity_id not in visible or r.object_entity_id not in visible:
                continue
            if not r.evidence_document_id or r.evidence_document_id not in allowed_docs:
                continue
            edge_ids.add(r.id)
            edges.append(r)
            for nid in (r.subject_entity_id, r.object_entity_id):
                if nid not in seen_nodes:
                    seen_nodes.add(nid)
                    next_frontier.add(nid)
            if len(edges) >= limit:
                break
        frontier = next_frontier
        if len(edges) >= limit:
            break
    node_ids = seen_nodes - {entity_id}
    nodes = list(
        db.scalars(
            select(Entity).where(Entity.tenant_id == tenant_id, Entity.id.in_(node_ids))
        ).all()
    ) if node_ids else []
    return NeighborGraph(center=center, nodes=nodes, edges=edges[:limit])


def list_relations(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    subject_id: str | None = None,
    object_id: str | None = None,
    predicate: str | None = None,
    limit: int = 50,
) -> list[Relation]:
    visible = visible_entity_ids(db, tenant_id=tenant_id, user_id=user_id)
    allowed = readable_document_ids(db, tenant_id=tenant_id, user_id=user_id)
    if not visible or not allowed:
        return []
    stmt = select(Relation).where(
        Relation.tenant_id == tenant_id,
        Relation.subject_entity_id.in_(visible),
        Relation.object_entity_id.in_(visible),
        Relation.evidence_document_id.in_(allowed),
    )
    if subject_id:
        stmt = stmt.where(Relation.subject_entity_id == subject_id)
    if object_id:
        stmt = stmt.where(Relation.object_entity_id == object_id)
    if predicate:
        pred, _ = normalize_predicate(predicate)
        stmt = stmt.where(Relation.predicate == pred)
    stmt = stmt.order_by(Relation.created_at.desc()).limit(min(limit, 100))
    return list(db.scalars(stmt).all())


def graph_stats(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
) -> dict[str, int]:
    visible = visible_entity_ids(db, tenant_id=tenant_id, user_id=user_id)
    allowed = readable_document_ids(db, tenant_id=tenant_id, user_id=user_id)
    entity_count = len(visible)
    relation_count = 0
    docs_covered = 0
    if visible and allowed:
        relation_count = int(
            db.scalar(
                select(func.count())
                .select_from(Relation)
                .where(
                    Relation.tenant_id == tenant_id,
                    Relation.subject_entity_id.in_(visible),
                    Relation.object_entity_id.in_(visible),
                    Relation.evidence_document_id.in_(allowed),
                )
            )
            or 0
        )
        docs_covered = int(
            db.scalar(
                select(func.count(func.distinct(EntityMention.document_id))).where(
                    EntityMention.tenant_id == tenant_id,
                    EntityMention.document_id.in_(allowed),
                )
            )
            or 0
        )
    return {
        "entities": entity_count,
        "relations": relation_count,
        "documents_covered": docs_covered,
    }


def match_entities_in_text(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    text: str,
    limit: int = 5,
) -> list[Entity]:
    visible = list_entities(db, tenant_id=tenant_id, user_id=user_id, limit=200)
    q = normalize_name(text)
    scored: list[tuple[int, Entity]] = []
    for ent in visible:
        name = ent.canonical_name
        if len(name) < 2:
            continue
        if name in q:
            scored.append((len(name), ent))
    scored.sort(key=lambda x: -x[0])
    out: list[Entity] = []
    seen: set[str] = set()
    for _, ent in scored:
        if ent.id in seen:
            continue
        seen.add(ent.id)
        out.append(ent)
        if len(out) >= limit:
            break
    return out


def serialize_graph_context(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    question: str,
) -> list[str]:
    ents = match_entities_in_text(db, tenant_id=tenant_id, user_id=user_id, text=question)
    blocks: list[str] = []
    for ent in ents:
        ng = neighbors(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            entity_id=ent.id,
            depth=1,
            limit=20,
        )
        if ng is None or not ng.edges:
            blocks.append(f"Entity: {ent.name} ({ent.type})")
            continue
        by_id = {ent.id: ent, **{n.id: n for n in ng.nodes}}
        lines = [f"Entity: {ent.name} ({ent.type})"]
        for edge in ng.edges:
            s = by_id.get(edge.subject_entity_id)
            o = by_id.get(edge.object_entity_id)
            if not s or not o:
                continue
            lines.append(f"- {s.name} —{edge.predicate}→ {o.name}")
        blocks.append("\n".join(lines))
    return blocks
