"""Education knowledge-base domain: packs, points, questions, explain, practice."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.acl import can_read_document, readable_document_ids
from shared.config import get_settings
from shared.db.models import (
    AuditEvent,
    Chunk,
    Document,
    EduContentPack,
    EduDocumentMeta,
    EduKnowledgePoint,
    EduPracticeItem,
    EduPracticeSession,
    EduQuestion,
    EduQuestionAnchor,
    EduQuestionPoint,
)
from shared.errors import AppError, ErrorCode
from shared.llm import gateway_complete
from shared.search import search_chunks

LICENSE_TYPES = frozenset({"owned", "licensed", "open", "demo"})
STAGES = frozenset({"primary", "junior"})
SUBJECTS = frozenset(
    {
        "chinese",
        "math",
        "english",
        "physics",
        "chemistry",
        "biology",
        "history",
        "geography",
        "politics",
        "science",
        "other",
    }
)
QTYPES = frozenset({"single", "multi", "fill", "judge", "essay", "calc"})
PRACTICE_MODES = frozenset({"drill", "explain", "exam"})


def require_edu_enabled() -> None:
    if not get_settings().edu_enabled:
        raise AppError(
            ErrorCode.FORBIDDEN,
            "education module disabled (set EDU_ENABLED=true)",
            status_code=403,
        )


def _norm_license(license_type: str) -> str:
    value = (license_type or "").strip().lower()
    if get_settings().edu_require_license and not value:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "license_type is required for content packs",
            status_code=400,
        )
    if value not in LICENSE_TYPES:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            f"invalid license_type; expected one of {sorted(LICENSE_TYPES)}",
            status_code=400,
        )
    return value


def _norm_stage(stage: str) -> str:
    value = (stage or "").strip().lower() or get_settings().edu_default_stage
    if value not in STAGES:
        raise AppError(ErrorCode.VALIDATION_ERROR, "invalid stage", status_code=400)
    return value


def _norm_subject(subject: str) -> str:
    value = (subject or "").strip().lower()
    if value not in SUBJECTS:
        raise AppError(ErrorCode.VALIDATION_ERROR, "invalid subject", status_code=400)
    return value


def _norm_qtype(qtype: str) -> str:
    value = (qtype or "").strip().lower()
    if value not in QTYPES:
        raise AppError(ErrorCode.VALIDATION_ERROR, "invalid qtype", status_code=400)
    return value


def create_pack(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    name: str,
    stage: str,
    subject: str,
    license_type: str,
    license_note: str = "",
    edition: str = "",
    grade_min: int | None = None,
    grade_max: int | None = None,
) -> EduContentPack:
    require_edu_enabled()
    pack = EduContentPack(
        tenant_id=tenant_id,
        name=name.strip(),
        stage=_norm_stage(stage),
        subject=_norm_subject(subject),
        grade_min=grade_min,
        grade_max=grade_max,
        edition=(edition or "").strip(),
        license_type=_norm_license(license_type),
        license_note=(license_note or "").strip(),
        status="active",
    )
    if not pack.name:
        raise AppError(ErrorCode.VALIDATION_ERROR, "pack name required", status_code=400)
    db.add(pack)
    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_id=user_id,
            action="edu.pack.create",
            resource_type="edu_content_pack",
            resource_id=pack.id,
            detail=json.dumps({"name": pack.name, "license_type": pack.license_type}, ensure_ascii=False),
        )
    )
    db.commit()
    db.refresh(pack)
    return pack


def list_packs(db: Session, *, tenant_id: str) -> list[EduContentPack]:
    require_edu_enabled()
    return list(
        db.scalars(
            select(EduContentPack)
            .where(EduContentPack.tenant_id == tenant_id)
            .order_by(EduContentPack.created_at.desc())
        ).all()
    )


def get_pack(db: Session, *, tenant_id: str, pack_id: str) -> EduContentPack:
    require_edu_enabled()
    pack = db.get(EduContentPack, pack_id)
    if pack is None or pack.tenant_id != tenant_id:
        raise AppError(ErrorCode.NOT_FOUND, "pack not found", status_code=404)
    return pack


def upsert_document_meta(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    document_id: str,
    stage: str,
    subject: str,
    grade: int,
    pack_id: str | None = None,
    edition: str = "",
    volume: str = "",
    unit_no: str = "",
    lesson_title: str = "",
    curriculum_code: str = "",
) -> EduDocumentMeta:
    require_edu_enabled()
    doc = db.get(Document, document_id)
    if doc is None or doc.tenant_id != tenant_id:
        raise AppError(ErrorCode.NOT_FOUND, "document not found", status_code=404)
    if pack_id:
        get_pack(db, tenant_id=tenant_id, pack_id=pack_id)
    if grade < 1 or grade > 9:
        raise AppError(ErrorCode.VALIDATION_ERROR, "grade must be 1..9", status_code=400)
    meta = db.get(EduDocumentMeta, document_id)
    if meta is None:
        meta = EduDocumentMeta(document_id=document_id, tenant_id=tenant_id)
        db.add(meta)
    meta.pack_id = pack_id
    meta.stage = _norm_stage(stage)
    meta.subject = _norm_subject(subject)
    meta.grade = grade
    meta.edition = (edition or "").strip()
    meta.volume = (volume or "").strip()
    meta.unit_no = (unit_no or "").strip()
    meta.lesson_title = (lesson_title or "").strip()
    meta.curriculum_code = (curriculum_code or "").strip()
    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_id=user_id,
            action="edu.document_meta.upsert",
            resource_type="document",
            resource_id=document_id,
            detail=json.dumps({"subject": meta.subject, "grade": meta.grade}, ensure_ascii=False),
        )
    )
    db.commit()
    db.refresh(meta)
    return meta


def upsert_point(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    name: str,
    subject: str,
    stage: str,
    code: str = "",
    pack_id: str | None = None,
    grade: int | None = None,
    parent_id: str | None = None,
    point_id: str | None = None,
) -> EduKnowledgePoint:
    require_edu_enabled()
    subject_n = _norm_subject(subject)
    stage_n = _norm_stage(stage)
    name_n = name.strip()
    code_n = (code or "").strip()
    if not name_n:
        raise AppError(ErrorCode.VALIDATION_ERROR, "knowledge point name required", status_code=400)
    if pack_id:
        get_pack(db, tenant_id=tenant_id, pack_id=pack_id)
    if parent_id:
        parent = db.get(EduKnowledgePoint, parent_id)
        if parent is None or parent.tenant_id != tenant_id:
            raise AppError(ErrorCode.NOT_FOUND, "parent point not found", status_code=404)

    point: EduKnowledgePoint | None = None
    if point_id:
        point = db.get(EduKnowledgePoint, point_id)
        if point is None or point.tenant_id != tenant_id:
            raise AppError(ErrorCode.NOT_FOUND, "knowledge point not found", status_code=404)
    else:
        point = db.scalar(
            select(EduKnowledgePoint).where(
                EduKnowledgePoint.tenant_id == tenant_id,
                EduKnowledgePoint.subject == subject_n,
                EduKnowledgePoint.code == code_n,
                EduKnowledgePoint.name == name_n,
            )
        )

    if point is None:
        point = EduKnowledgePoint(tenant_id=tenant_id)
        db.add(point)

    point.pack_id = pack_id
    point.code = code_n
    point.name = name_n
    point.subject = subject_n
    point.stage = stage_n
    point.grade = grade
    point.parent_id = parent_id
    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_id=user_id,
            action="edu.point.upsert",
            resource_type="edu_knowledge_point",
            resource_id=point.id,
            detail=json.dumps({"name": point.name, "code": point.code}, ensure_ascii=False),
        )
    )
    db.commit()
    db.refresh(point)
    return point


def list_points(
    db: Session,
    *,
    tenant_id: str,
    subject: str | None = None,
    pack_id: str | None = None,
) -> list[EduKnowledgePoint]:
    require_edu_enabled()
    stmt = select(EduKnowledgePoint).where(EduKnowledgePoint.tenant_id == tenant_id)
    if subject:
        stmt = stmt.where(EduKnowledgePoint.subject == _norm_subject(subject))
    if pack_id:
        stmt = stmt.where(EduKnowledgePoint.pack_id == pack_id)
    return list(db.scalars(stmt.order_by(EduKnowledgePoint.code, EduKnowledgePoint.name)).all())


def _serialize_options(options: list[str] | None) -> str:
    return json.dumps(options or [], ensure_ascii=False)


def create_question(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    stem_md: str,
    qtype: str,
    subject: str,
    stage: str,
    answer_md: str = "",
    analysis_md: str = "",
    options: list[str] | None = None,
    difficulty: int = 3,
    grade: int | None = None,
    pack_id: str | None = None,
    source_doc_id: str | None = None,
    knowledge_point_ids: list[str] | None = None,
    anchors: list[dict] | None = None,
) -> EduQuestion:
    require_edu_enabled()
    stem = stem_md.strip()
    if not stem:
        raise AppError(ErrorCode.VALIDATION_ERROR, "stem_md required", status_code=400)
    if difficulty < 1 or difficulty > 5:
        raise AppError(ErrorCode.VALIDATION_ERROR, "difficulty must be 1..5", status_code=400)
    if pack_id:
        get_pack(db, tenant_id=tenant_id, pack_id=pack_id)

    q = EduQuestion(
        tenant_id=tenant_id,
        pack_id=pack_id,
        stem_md=stem,
        options_json=_serialize_options(options),
        answer_md=(answer_md or "").strip(),
        analysis_md=(analysis_md or "").strip(),
        qtype=_norm_qtype(qtype),
        difficulty=difficulty,
        grade=grade,
        subject=_norm_subject(subject),
        stage=_norm_stage(stage),
        source_doc_id=source_doc_id,
        status="active",
    )
    db.add(q)
    db.flush()

    for kid in knowledge_point_ids or []:
        point = db.get(EduKnowledgePoint, kid)
        if point is None or point.tenant_id != tenant_id:
            raise AppError(ErrorCode.NOT_FOUND, f"knowledge point not found: {kid}", status_code=404)
        db.add(EduQuestionPoint(question_id=q.id, knowledge_point_id=kid, weight=1.0))

    for a in anchors or []:
        document_id = str(a.get("document_id") or "").strip()
        if not document_id:
            continue
        doc = db.get(Document, document_id)
        if doc is None or doc.tenant_id != tenant_id:
            raise AppError(ErrorCode.NOT_FOUND, "anchor document not found", status_code=404)
        chunk_id = a.get("chunk_id")
        if chunk_id:
            chunk = db.get(Chunk, str(chunk_id))
            if chunk is None or chunk.tenant_id != tenant_id or chunk.document_id != document_id:
                raise AppError(ErrorCode.NOT_FOUND, "anchor chunk not found", status_code=404)
        db.add(
            EduQuestionAnchor(
                question_id=q.id,
                document_id=document_id,
                chunk_id=str(chunk_id) if chunk_id else None,
                note=str(a.get("note") or ""),
            )
        )

    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_id=user_id,
            action="edu.question.create",
            resource_type="edu_question",
            resource_id=q.id,
            detail=json.dumps({"subject": q.subject, "qtype": q.qtype}, ensure_ascii=False),
        )
    )
    db.commit()
    db.refresh(q)
    return q


def list_questions(
    db: Session,
    *,
    tenant_id: str,
    subject: str | None = None,
    stage: str | None = None,
    grade: int | None = None,
    pack_id: str | None = None,
    knowledge_point_id: str | None = None,
    difficulty: int | None = None,
    limit: int = 50,
) -> list[EduQuestion]:
    require_edu_enabled()
    stmt = select(EduQuestion).where(
        EduQuestion.tenant_id == tenant_id,
        EduQuestion.status == "active",
    )
    if subject:
        stmt = stmt.where(EduQuestion.subject == _norm_subject(subject))
    if stage:
        stmt = stmt.where(EduQuestion.stage == _norm_stage(stage))
    if grade is not None:
        stmt = stmt.where(EduQuestion.grade == grade)
    if pack_id:
        stmt = stmt.where(EduQuestion.pack_id == pack_id)
    if difficulty is not None:
        stmt = stmt.where(EduQuestion.difficulty == difficulty)
    if knowledge_point_id:
        stmt = (
            stmt.join(
                EduQuestionPoint,
                EduQuestionPoint.question_id == EduQuestion.id,
            ).where(EduQuestionPoint.knowledge_point_id == knowledge_point_id)
        )
    rows = list(db.scalars(stmt.order_by(EduQuestion.created_at.desc()).limit(max(1, min(limit, 200)))).all())
    return rows


def get_question(db: Session, *, tenant_id: str, question_id: str) -> EduQuestion:
    require_edu_enabled()
    q = db.get(EduQuestion, question_id)
    if q is None or q.tenant_id != tenant_id or q.status != "active":
        raise AppError(ErrorCode.NOT_FOUND, "question not found", status_code=404)
    return q


def question_point_ids(db: Session, *, question_id: str) -> list[str]:
    return list(
        db.scalars(
            select(EduQuestionPoint.knowledge_point_id).where(
                EduQuestionPoint.question_id == question_id
            )
        ).all()
    )


def question_anchors(db: Session, *, question_id: str) -> list[EduQuestionAnchor]:
    return list(
        db.scalars(
            select(EduQuestionAnchor).where(EduQuestionAnchor.question_id == question_id)
        ).all()
    )


def parse_options(q: EduQuestion) -> list[str]:
    try:
        data = json.loads(q.options_json or "[]")
        if isinstance(data, list):
            return [str(x) for x in data]
    except json.JSONDecodeError:
        pass
    return []


@dataclass
class ExplainResult:
    answer: str
    question_id: str
    citations: list[dict]
    knowledge_point_ids: list[str]


def explain_question(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    question_id: str | None = None,
    stem_md: str | None = None,
    limit: int = 5,
) -> ExplainResult:
    require_edu_enabled()
    q: EduQuestion | None = None
    point_ids: list[str] = []
    analysis = ""
    answer_key = ""
    stem = (stem_md or "").strip()

    if question_id:
        q = get_question(db, tenant_id=tenant_id, question_id=question_id)
        stem = q.stem_md
        analysis = q.analysis_md or ""
        answer_key = q.answer_md or ""
        point_ids = question_point_ids(db, question_id=q.id)
    if not stem:
        raise AppError(ErrorCode.VALIDATION_ERROR, "question_id or stem_md required", status_code=400)

    context_blocks: list[str] = []
    citations: list[dict] = []

    if analysis:
        context_blocks.append(f"[题目解析]\n{analysis}")
    if answer_key:
        context_blocks.append(f"[参考答案]\n{answer_key}")

    if point_ids:
        points = db.scalars(
            select(EduKnowledgePoint).where(
                EduKnowledgePoint.tenant_id == tenant_id,
                EduKnowledgePoint.id.in_(point_ids),
            )
        ).all()
        if points:
            lines = [f"- {p.code + ' ' if p.code else ''}{p.name}" for p in points]
            context_blocks.append("[知识点]\n" + "\n".join(lines))

    allowed = readable_document_ids(db, tenant_id=tenant_id, user_id=user_id)
    if q:
        for anchor in question_anchors(db, question_id=q.id):
            if anchor.document_id not in allowed:
                continue
            if anchor.chunk_id:
                chunk = db.get(Chunk, anchor.chunk_id)
                if (
                    chunk
                    and chunk.tenant_id == tenant_id
                    and chunk.document_id == anchor.document_id
                    and chunk.status == "active"
                ):
                    context_blocks.append(f"[教材锚点]\n{chunk.content}")
                    citations.append(
                        {
                            "chunk_id": chunk.id,
                            "document_id": chunk.document_id,
                            "snippet": chunk.content[:240],
                            "source": "anchor",
                        }
                    )
            elif can_read_document(
                db, tenant_id=tenant_id, user_id=user_id, document_id=anchor.document_id
            ):
                context_blocks.append(f"[教材文档] document_id={anchor.document_id} {anchor.note}")

    hits = search_chunks(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        query=stem[:500],
        limit=max(1, min(limit, 10)),
    )
    for h in hits:
        context_blocks.append(h.content)
        citations.append(
            {
                "chunk_id": h.chunk_id,
                "document_id": h.document_id,
                "snippet": h.content[:240],
                "source": "search",
                "score": h.score,
            }
        )

    prompt = (
        "请讲解下面这道题：给出清晰步骤、易错点，并在有证据时引用教材/解析。"
        f"\n\n题干：\n{stem}"
    )
    answer = gateway_complete(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        prompt=prompt,
        context_blocks=context_blocks,
        operation="ask",
        sensitivity="L2",
        purpose="edu_explain",
    )
    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_id=user_id,
            action="edu.explain",
            resource_type="edu_question",
            resource_id=q.id if q else "",
            detail=json.dumps({"citations": len(citations), "points": len(point_ids)}, ensure_ascii=False),
        )
    )
    db.commit()
    return ExplainResult(
        answer=answer,
        question_id=q.id if q else "",
        citations=citations,
        knowledge_point_ids=point_ids,
    )


def similar_questions(
    db: Session,
    *,
    tenant_id: str,
    question_id: str,
    top_k: int | None = None,
) -> list[EduQuestion]:
    require_edu_enabled()
    q = get_question(db, tenant_id=tenant_id, question_id=question_id)
    k = top_k or get_settings().edu_similar_top_k
    point_ids = set(question_point_ids(db, question_id=q.id))
    candidates = list_questions(
        db,
        tenant_id=tenant_id,
        subject=q.subject,
        stage=q.stage,
        limit=100,
    )
    scored: list[tuple[float, EduQuestion]] = []
    for other in candidates:
        if other.id == q.id:
            continue
        other_points = set(question_point_ids(db, question_id=other.id))
        overlap = len(point_ids & other_points)
        diff_penalty = abs((other.difficulty or 3) - (q.difficulty or 3)) * 0.15
        score = overlap * 2.0 - diff_penalty
        if overlap == 0 and other.grade == q.grade:
            score += 0.3
        if score > 0:
            scored.append((score, other))
    scored.sort(key=lambda x: (-x[0], x[1].difficulty))
    return [row for _, row in scored[: max(1, min(k, 20))]]


def start_practice(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    mode: str = "drill",
    workspace_id: str | None = None,
    filters: dict | None = None,
    question_ids: list[str] | None = None,
    limit: int = 5,
) -> tuple[EduPracticeSession, list[EduQuestion]]:
    require_edu_enabled()
    mode_n = (mode or "drill").strip().lower()
    if mode_n not in PRACTICE_MODES:
        raise AppError(ErrorCode.VALIDATION_ERROR, "invalid practice mode", status_code=400)
    filters = filters or {}
    if question_ids:
        questions = [get_question(db, tenant_id=tenant_id, question_id=qid) for qid in question_ids]
    else:
        questions = list_questions(
            db,
            tenant_id=tenant_id,
            subject=filters.get("subject"),
            stage=filters.get("stage"),
            grade=filters.get("grade"),
            pack_id=filters.get("pack_id"),
            knowledge_point_id=filters.get("knowledge_point_id"),
            difficulty=filters.get("difficulty"),
            limit=limit,
        )
    session = EduPracticeSession(
        tenant_id=tenant_id,
        user_id=user_id,
        workspace_id=workspace_id,
        mode=mode_n,
        filter_json=json.dumps(filters, ensure_ascii=False),
    )
    db.add(session)
    db.flush()
    for q in questions:
        db.add(EduPracticeItem(session_id=session.id, question_id=q.id))
    db.commit()
    db.refresh(session)
    return session, questions


def _normalize_answer(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"\s+", "", t)
    return t


def grade_answer(q: EduQuestion, user_answer: str) -> int | None:
    """Return 1/0 for auto-gradable types; None for essay/calc."""
    if q.qtype in {"essay", "calc"}:
        return None
    expected = _normalize_answer(q.answer_md)
    got = _normalize_answer(user_answer)
    if not expected:
        return None
    if q.qtype == "multi":
        exp_parts = sorted(p for p in re.split(r"[,，、;/\|]", expected) if p)
        got_parts = sorted(p for p in re.split(r"[,，、;/\|]", got) if p)
        return 1 if exp_parts == got_parts else 0
    return 1 if expected == got else 0


def submit_practice_answer(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    session_id: str,
    question_id: str,
    user_answer_md: str,
) -> EduPracticeItem:
    require_edu_enabled()
    session = db.get(EduPracticeSession, session_id)
    if session is None or session.tenant_id != tenant_id or session.user_id != user_id:
        raise AppError(ErrorCode.NOT_FOUND, "practice session not found", status_code=404)
    q = get_question(db, tenant_id=tenant_id, question_id=question_id)
    item = db.scalar(
        select(EduPracticeItem).where(
            EduPracticeItem.session_id == session_id,
            EduPracticeItem.question_id == question_id,
        )
    )
    if item is None:
        item = EduPracticeItem(session_id=session_id, question_id=question_id)
        db.add(item)
    item.user_answer_md = user_answer_md or ""
    item.is_correct = grade_answer(q, item.user_answer_md)
    db.commit()
    db.refresh(item)
    return item


def seed_junior_math_demo(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
) -> dict:
    """Idempotent demo pack: 初中数学七年级样例（license=demo）。"""
    require_edu_enabled()
    existing = db.scalar(
        select(EduContentPack).where(
            EduContentPack.tenant_id == tenant_id,
            EduContentPack.license_type == "demo",
            EduContentPack.subject == "math",
            EduContentPack.name == "试点·初中数学七年级上（演示）",
        )
    )
    if existing:
        questions = list_questions(db, tenant_id=tenant_id, pack_id=existing.id, limit=50)
        points = list_points(db, tenant_id=tenant_id, pack_id=existing.id)
        return {
            "pack_id": existing.id,
            "created": False,
            "points": len(points),
            "questions": len(questions),
        }

    pack = create_pack(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        name="试点·初中数学七年级上（演示）",
        stage="junior",
        subject="math",
        license_type="demo",
        license_note="内置演示样例，非出版社正版教材全文",
        edition="演示版",
        grade_min=7,
        grade_max=7,
    )
    p_rational = upsert_point(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        name="有理数运算",
        code="MATH-7-01",
        subject="math",
        stage="junior",
        grade=7,
        pack_id=pack.id,
    )
    p_eq = upsert_point(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        name="一元一次方程",
        code="MATH-7-02",
        subject="math",
        stage="junior",
        grade=7,
        pack_id=pack.id,
    )
    samples = [
        {
            "stem_md": "计算：$(-3)+5=$？",
            "qtype": "fill",
            "answer_md": "2",
            "analysis_md": "异号两数相加，取绝对值较大的符号，并用较大绝对值减去较小绝对值：$5-3=2$。",
            "difficulty": 1,
            "points": [p_rational.id],
        },
        {
            "stem_md": "下列哪个是有理数？",
            "qtype": "single",
            "options": ["√2", "π", "-3/4", "√(-1)"],
            "answer_md": "C",
            "analysis_md": "有理数可写成整数之比；-3/4 是分数。√2、π 是无理数；√(-1) 不是实数范围内的有理数。",
            "difficulty": 2,
            "points": [p_rational.id],
        },
        {
            "stem_md": "解方程：$2x+3=11$。",
            "qtype": "fill",
            "answer_md": "4",
            "analysis_md": "移项得 $2x=8$，两边同除以 2 得 $x=4$。",
            "difficulty": 2,
            "points": [p_eq.id],
        },
        {
            "stem_md": "方程 $3(x-1)=2x+5$ 的解是？",
            "qtype": "single",
            "options": ["x=2", "x=8", "x=-2", "x=5"],
            "answer_md": "B",
            "analysis_md": "展开：$3x-3=2x+5$，移项 $3x-2x=5+3$，得 $x=8$。",
            "difficulty": 3,
            "points": [p_eq.id],
        },
        {
            "stem_md": "判断：任意两个有理数的和仍是有理数。（对/错）",
            "qtype": "judge",
            "answer_md": "对",
            "analysis_md": "有理数集对加法封闭。",
            "difficulty": 1,
            "points": [p_rational.id],
        },
    ]
    for s in samples:
        create_question(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            stem_md=s["stem_md"],
            qtype=s["qtype"],
            subject="math",
            stage="junior",
            grade=7,
            pack_id=pack.id,
            answer_md=s["answer_md"],
            analysis_md=s["analysis_md"],
            options=s.get("options"),
            difficulty=s["difficulty"],
            knowledge_point_ids=s["points"],
        )
    return {
        "pack_id": pack.id,
        "created": True,
        "points": 2,
        "questions": len(samples),
    }
