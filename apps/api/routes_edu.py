from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from shared.db import get_db
from shared.education import (
    create_pack,
    create_question,
    explain_question,
    get_question,
    list_packs,
    list_points,
    list_questions,
    parse_options,
    question_anchors,
    question_point_ids,
    seed_junior_math_demo,
    similar_questions,
    start_practice,
    submit_practice_answer,
    upsert_document_meta,
    upsert_point,
)
from sqlalchemy.orm import Session

from api.auth import AuthContext, get_current_auth

router = APIRouter(prefix="/v1/edu", tags=["education"])


class PackCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    stage: str
    subject: str
    license_type: str
    license_note: str = ""
    edition: str = ""
    grade_min: int | None = None
    grade_max: int | None = None


class PackOut(BaseModel):
    id: str
    name: str
    stage: str
    subject: str
    grade_min: int | None
    grade_max: int | None
    edition: str
    license_type: str
    license_note: str
    status: str


class DocumentMetaIn(BaseModel):
    stage: str
    subject: str
    grade: int
    pack_id: str | None = None
    edition: str = ""
    volume: str = ""
    unit_no: str = ""
    lesson_title: str = ""
    curriculum_code: str = ""


class DocumentMetaOut(BaseModel):
    document_id: str
    pack_id: str | None
    stage: str
    subject: str
    grade: int
    edition: str
    volume: str
    unit_no: str
    lesson_title: str
    curriculum_code: str


class PointIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    subject: str
    stage: str
    code: str = ""
    pack_id: str | None = None
    grade: int | None = None
    parent_id: str | None = None
    id: str | None = None


class PointOut(BaseModel):
    id: str
    name: str
    code: str
    subject: str
    stage: str
    grade: int | None
    pack_id: str | None
    parent_id: str | None


class AnchorIn(BaseModel):
    document_id: str
    chunk_id: str | None = None
    note: str = ""


class QuestionIn(BaseModel):
    stem_md: str = Field(min_length=1)
    qtype: str
    subject: str
    stage: str
    answer_md: str = ""
    analysis_md: str = ""
    options: list[str] = Field(default_factory=list)
    difficulty: int = 3
    grade: int | None = None
    pack_id: str | None = None
    source_doc_id: str | None = None
    knowledge_point_ids: list[str] = Field(default_factory=list)
    anchors: list[AnchorIn] = Field(default_factory=list)


class QuestionBatchIn(BaseModel):
    questions: list[QuestionIn] = Field(min_length=1, max_length=100)


class AnchorOut(BaseModel):
    id: str
    document_id: str
    chunk_id: str | None
    note: str


class QuestionOut(BaseModel):
    id: str
    stem_md: str
    options: list[str]
    answer_md: str
    analysis_md: str
    qtype: str
    difficulty: int
    grade: int | None
    subject: str
    stage: str
    pack_id: str | None
    knowledge_point_ids: list[str]
    anchors: list[AnchorOut] = Field(default_factory=list)


class ExplainIn(BaseModel):
    question_id: str | None = None
    stem_md: str | None = None
    limit: int = 5


class CitationOut(BaseModel):
    chunk_id: str | None = None
    document_id: str | None = None
    snippet: str = ""
    source: str = ""
    score: float | None = None


class ExplainOut(BaseModel):
    answer: str
    question_id: str
    citations: list[CitationOut]
    knowledge_point_ids: list[str]


class PracticeIn(BaseModel):
    mode: str = "drill"
    workspace_id: str | None = None
    filters: dict = Field(default_factory=dict)
    question_ids: list[str] = Field(default_factory=list)
    limit: int = 5


class PracticeOut(BaseModel):
    session_id: str
    mode: str
    questions: list[QuestionOut]


class PracticeAnswerIn(BaseModel):
    question_id: str
    user_answer_md: str = ""


class PracticeAnswerOut(BaseModel):
    id: str
    session_id: str
    question_id: str
    user_answer_md: str
    is_correct: int | None


class SeedOut(BaseModel):
    pack_id: str
    created: bool
    points: int
    questions: int


def _pack_out(p) -> PackOut:
    return PackOut(
        id=p.id,
        name=p.name,
        stage=p.stage,
        subject=p.subject,
        grade_min=p.grade_min,
        grade_max=p.grade_max,
        edition=p.edition or "",
        license_type=p.license_type,
        license_note=p.license_note or "",
        status=p.status,
    )


def _point_out(p) -> PointOut:
    return PointOut(
        id=p.id,
        name=p.name,
        code=p.code or "",
        subject=p.subject,
        stage=p.stage,
        grade=p.grade,
        pack_id=p.pack_id,
        parent_id=p.parent_id,
    )


def _question_out(db: Session, q, *, include_anchors: bool = False) -> QuestionOut:
    anchors: list[AnchorOut] = []
    if include_anchors:
        anchors = [
            AnchorOut(
                id=a.id,
                document_id=a.document_id,
                chunk_id=a.chunk_id,
                note=a.note or "",
            )
            for a in question_anchors(db, question_id=q.id)
        ]
    return QuestionOut(
        id=q.id,
        stem_md=q.stem_md,
        options=parse_options(q),
        answer_md=q.answer_md or "",
        analysis_md=q.analysis_md or "",
        qtype=q.qtype,
        difficulty=q.difficulty,
        grade=q.grade,
        subject=q.subject,
        stage=q.stage,
        pack_id=q.pack_id,
        knowledge_point_ids=question_point_ids(db, question_id=q.id),
        anchors=anchors,
    )


@router.post("/packs", response_model=PackOut)
def api_create_pack(
    body: PackCreate,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> PackOut:
    pack = create_pack(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        name=body.name,
        stage=body.stage,
        subject=body.subject,
        license_type=body.license_type,
        license_note=body.license_note,
        edition=body.edition,
        grade_min=body.grade_min,
        grade_max=body.grade_max,
    )
    return _pack_out(pack)


@router.get("/packs", response_model=list[PackOut])
def api_list_packs(
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> list[PackOut]:
    return [_pack_out(p) for p in list_packs(db, tenant_id=auth.tenant_id)]


@router.post("/packs/seed-demo", response_model=SeedOut)
def api_seed_demo(
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> SeedOut:
    result = seed_junior_math_demo(db, tenant_id=auth.tenant_id, user_id=auth.user_id)
    return SeedOut(**result)


@router.post("/documents/{document_id}/meta", response_model=DocumentMetaOut)
def api_document_meta(
    document_id: str,
    body: DocumentMetaIn,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> DocumentMetaOut:
    meta = upsert_document_meta(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        document_id=document_id,
        stage=body.stage,
        subject=body.subject,
        grade=body.grade,
        pack_id=body.pack_id,
        edition=body.edition,
        volume=body.volume,
        unit_no=body.unit_no,
        lesson_title=body.lesson_title,
        curriculum_code=body.curriculum_code,
    )
    return DocumentMetaOut(
        document_id=meta.document_id,
        pack_id=meta.pack_id,
        stage=meta.stage,
        subject=meta.subject,
        grade=meta.grade,
        edition=meta.edition or "",
        volume=meta.volume or "",
        unit_no=meta.unit_no or "",
        lesson_title=meta.lesson_title or "",
        curriculum_code=meta.curriculum_code or "",
    )


@router.post("/points", response_model=PointOut)
def api_upsert_point(
    body: PointIn,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> PointOut:
    point = upsert_point(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        name=body.name,
        subject=body.subject,
        stage=body.stage,
        code=body.code,
        pack_id=body.pack_id,
        grade=body.grade,
        parent_id=body.parent_id,
        point_id=body.id,
    )
    return _point_out(point)


@router.get("/points", response_model=list[PointOut])
def api_list_points(
    subject: str | None = None,
    pack_id: str | None = None,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> list[PointOut]:
    return [
        _point_out(p)
        for p in list_points(db, tenant_id=auth.tenant_id, subject=subject, pack_id=pack_id)
    ]


@router.post("/questions", response_model=QuestionOut)
def api_create_question(
    body: QuestionIn,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> QuestionOut:
    q = create_question(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        stem_md=body.stem_md,
        qtype=body.qtype,
        subject=body.subject,
        stage=body.stage,
        answer_md=body.answer_md,
        analysis_md=body.analysis_md,
        options=body.options,
        difficulty=body.difficulty,
        grade=body.grade,
        pack_id=body.pack_id,
        source_doc_id=body.source_doc_id,
        knowledge_point_ids=body.knowledge_point_ids,
        anchors=[a.model_dump() for a in body.anchors],
    )
    return _question_out(db, q, include_anchors=True)


@router.post("/questions/batch", response_model=list[QuestionOut])
def api_create_questions_batch(
    body: QuestionBatchIn,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> list[QuestionOut]:
    out: list[QuestionOut] = []
    for item in body.questions:
        q = create_question(
            db,
            tenant_id=auth.tenant_id,
            user_id=auth.user_id,
            stem_md=item.stem_md,
            qtype=item.qtype,
            subject=item.subject,
            stage=item.stage,
            answer_md=item.answer_md,
            analysis_md=item.analysis_md,
            options=item.options,
            difficulty=item.difficulty,
            grade=item.grade,
            pack_id=item.pack_id,
            source_doc_id=item.source_doc_id,
            knowledge_point_ids=item.knowledge_point_ids,
            anchors=[a.model_dump() for a in item.anchors],
        )
        out.append(_question_out(db, q, include_anchors=True))
    return out


@router.get("/questions", response_model=list[QuestionOut])
def api_list_questions(
    subject: str | None = None,
    stage: str | None = None,
    grade: int | None = None,
    pack_id: str | None = None,
    knowledge_point_id: str | None = None,
    difficulty: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> list[QuestionOut]:
    rows = list_questions(
        db,
        tenant_id=auth.tenant_id,
        subject=subject,
        stage=stage,
        grade=grade,
        pack_id=pack_id,
        knowledge_point_id=knowledge_point_id,
        difficulty=difficulty,
        limit=limit,
    )
    return [_question_out(db, q) for q in rows]


@router.get("/questions/{question_id}", response_model=QuestionOut)
def api_get_question(
    question_id: str,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> QuestionOut:
    q = get_question(db, tenant_id=auth.tenant_id, question_id=question_id)
    return _question_out(db, q, include_anchors=True)


@router.post("/explain", response_model=ExplainOut)
def api_explain(
    body: ExplainIn,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> ExplainOut:
    result = explain_question(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        question_id=body.question_id,
        stem_md=body.stem_md,
        limit=body.limit,
    )
    return ExplainOut(
        answer=result.answer,
        question_id=result.question_id,
        citations=[CitationOut(**c) for c in result.citations],
        knowledge_point_ids=result.knowledge_point_ids,
    )


@router.get("/similar", response_model=list[QuestionOut])
def api_similar(
    question_id: str = Query(...),
    top_k: int | None = None,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> list[QuestionOut]:
    rows = similar_questions(
        db, tenant_id=auth.tenant_id, question_id=question_id, top_k=top_k
    )
    return [_question_out(db, q) for q in rows]


@router.post("/practice", response_model=PracticeOut)
def api_practice(
    body: PracticeIn,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> PracticeOut:
    session, questions = start_practice(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        mode=body.mode,
        workspace_id=body.workspace_id,
        filters=body.filters,
        question_ids=body.question_ids or None,
        limit=body.limit,
    )
    return PracticeOut(
        session_id=session.id,
        mode=session.mode,
        questions=[_question_out(db, q) for q in questions],
    )


@router.post("/practice/{session_id}/answer", response_model=PracticeAnswerOut)
def api_practice_answer(
    session_id: str,
    body: PracticeAnswerIn,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> PracticeAnswerOut:
    item = submit_practice_answer(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        session_id=session_id,
        question_id=body.question_id,
        user_answer_md=body.user_answer_md,
    )
    return PracticeAnswerOut(
        id=item.id,
        session_id=item.session_id,
        question_id=item.question_id,
        user_answer_md=item.user_answer_md or "",
        is_correct=item.is_correct,
    )
