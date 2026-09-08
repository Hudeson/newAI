"""Official education website / open-feed fetchers.

Compliance rules:
- Only allowlisted official hosts (or explicitly licensed partner feeds).
- Sync requires accept_license=true and a declared license_type.
- Does not scrape arbitrary commercial exam banks or bypass paywalls.
- Default mode is fixture (offline-safe); set EDU_OFFICIAL_MODE=live to HTTP-fetch.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.acl import grant_default_acl
from shared.config import get_settings
from shared.db.models import (
    AuditEvent,
    Chunk,
    Document,
    DocumentVersion,
    EduContentPack,
    EduOfficialSyncJob,
    UploadJob,
    Workspace,
)
from shared.education import (
    create_pack,
    create_question,
    get_pack,
    list_packs,
    require_edu_enabled,
    upsert_document_meta,
    upsert_point,
)
from shared.errors import AppError, ErrorCode
from shared.ingest import chunk_text, embed_text, tokenize
from shared.storage import get_storage

# Official / public-education hosts commonly used for open curricula & notices.
DEFAULT_ALLOW_HOSTS = frozenset(
    {
        "www.moe.gov.cn",
        "moe.gov.cn",
        "www.smartedu.cn",
        "basic.smartedu.cn",
        "www.neea.edu.cn",
        "neea.edu.cn",
        "www.chinadegrees.cn",
        "localhost",
        "127.0.0.1",
    }
)


@dataclass(frozen=True)
class OfficialSource:
    id: str
    name: str
    provider: str
    stage: str
    subject: str
    grade: int | None
    license_type: str
    license_note: str
    feed_url: str
    format: str  # atrium_edu_json | fixture
    description: str = ""


@dataclass
class SyncResult:
    job_id: str
    source_id: str
    pack_id: str
    status: str
    tutorials_imported: int = 0
    questions_imported: int = 0
    points_imported: int = 0
    document_ids: list[str] = field(default_factory=list)
    question_ids: list[str] = field(default_factory=list)
    error: str = ""


def _allow_hosts() -> set[str]:
    settings = get_settings()
    hosts = set(DEFAULT_ALLOW_HOSTS)
    extra = (settings.edu_official_allow_hosts or "").strip()
    if extra:
        hosts.update(h.strip().lower() for h in extra.split(",") if h.strip())
    return hosts


def catalog_sources() -> list[OfficialSource]:
    """Built-in official / open education sources."""
    return [
        OfficialSource(
            id="fixture-moe-math-g7",
            name="课标公开样例·初中数学七年级",
            provider="教育部课标公开纲要（结构化样例）",
            stage="junior",
            subject="math",
            grade=7,
            license_type="open",
            license_note="公开课标知识点与示例题结构化样例；非出版社教材全文盗版",
            feed_url="fixture://moe-math-g7",
            format="fixture",
            description="离线安全样例，结构对齐官网公开课标 JSON 源",
        ),
        OfficialSource(
            id="fixture-smartedu-chinese-g7",
            name="智慧教育公开样例·初中语文七年级",
            provider="国家智慧教育公共服务平台（公开资源结构样例）",
            stage="junior",
            subject="chinese",
            grade=7,
            license_type="open",
            license_note="公开教学资源结构样例；实际拉取需白名单域名与授权",
            feed_url="fixture://smartedu-chinese-g7",
            format="fixture",
            description="教程章节 + 练习题的 atrium_edu_json 样例",
        ),
        OfficialSource(
            id="live-custom",
            name="自定义官方/授权 JSON 源",
            provider="客户配置的白名单官方源",
            stage="junior",
            subject="math",
            grade=None,
            license_type="licensed",
            license_note="须提供已授权或公开协议的 atrium_edu_json 地址",
            feed_url="",
            format="atrium_edu_json",
            description="POST sync 时传入 feed_url；主机必须在 EDU_OFFICIAL_ALLOW_HOSTS",
        ),
    ]


def get_source(source_id: str) -> OfficialSource:
    for s in catalog_sources():
        if s.id == source_id:
            return s
    raise AppError(ErrorCode.NOT_FOUND, f"official source not found: {source_id}", status_code=404)


def assert_url_allowed(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme == "fixture":
        return url
    if parsed.scheme not in {"http", "https"}:
        raise AppError(ErrorCode.VALIDATION_ERROR, "feed_url must be http(s) or fixture://", status_code=400)
    host = (parsed.hostname or "").lower()
    if host not in _allow_hosts():
        raise AppError(
            ErrorCode.FORBIDDEN,
            "feed host is not on the official education allowlist",
            status_code=403,
            details={"host": host, "allow_hosts": sorted(_allow_hosts())},
        )
    return url


def _fixture_payload(key: str) -> dict[str, Any]:
    if key == "moe-math-g7":
        return {
            "pack": {
                "name": "官方公开·初中数学七年级（课标样例）",
                "stage": "junior",
                "subject": "math",
                "edition": "课标公开纲要样例",
                "grade_min": 7,
                "grade_max": 7,
                "license_type": "open",
                "license_note": "结构化公开课标样例",
            },
            "points": [
                {"code": "MOE-M7-01", "name": "有理数", "grade": 7},
                {"code": "MOE-M7-02", "name": "整式的加减", "grade": 7},
                {"code": "MOE-M7-03", "name": "一元一次方程", "grade": 7},
            ],
            "tutorials": [
                {
                    "title": "有理数及其运算（公开教程纲要）",
                    "unit_no": "1",
                    "lesson_title": "有理数",
                    "body_md": (
                        "# 有理数\n\n"
                        "有理数包括整数和分数。掌握加减乘除与混合运算，注意符号法则。\n\n"
                        "## 要点\n"
                        "- 相反数与绝对值\n"
                        "- 异号两数相加\n"
                        "- 运算顺序\n"
                    ),
                },
                {
                    "title": "一元一次方程（公开教程纲要）",
                    "unit_no": "3",
                    "lesson_title": "一元一次方程",
                    "body_md": (
                        "# 一元一次方程\n\n"
                        "含有一个未知数、未知数次数是 1 的方程。\n\n"
                        "## 步骤\n"
                        "1. 去分母 / 去括号\n"
                        "2. 移项\n"
                        "3. 合并同类项\n"
                        "4. 系数化为 1\n"
                    ),
                },
            ],
            "questions": [
                {
                    "stem_md": "（公开样例）计算：$(-8)+3=$？",
                    "qtype": "fill",
                    "answer_md": "-5",
                    "analysis_md": "异号相加：绝对值大的符号，8-3=5，结果为 -5。",
                    "difficulty": 1,
                    "point_codes": ["MOE-M7-01"],
                },
                {
                    "stem_md": "（公开样例）方程 $x-4=9$ 的解是？",
                    "qtype": "single",
                    "options": ["x=5", "x=13", "x=-13", "x=36"],
                    "answer_md": "B",
                    "analysis_md": "移项得 x=9+4=13。",
                    "difficulty": 1,
                    "point_codes": ["MOE-M7-03"],
                },
                {
                    "stem_md": "（公开样例）化简：$3a+2a-a$",
                    "qtype": "fill",
                    "answer_md": "4a",
                    "analysis_md": "合并同类项：3+2-1=4，结果 4a。",
                    "difficulty": 2,
                    "point_codes": ["MOE-M7-02"],
                },
                {
                    "stem_md": "（公开样例）判断：有理数对乘法封闭。（对/错）",
                    "qtype": "judge",
                    "answer_md": "对",
                    "analysis_md": "任意两有理数之积仍为有理数。",
                    "difficulty": 2,
                    "point_codes": ["MOE-M7-01"],
                },
            ],
        }
    if key == "smartedu-chinese-g7":
        return {
            "pack": {
                "name": "智慧教育公开样例·初中语文七年级",
                "stage": "junior",
                "subject": "chinese",
                "edition": "公开资源结构样例",
                "grade_min": 7,
                "grade_max": 7,
                "license_type": "open",
                "license_note": "公开教学资源结构样例",
            },
            "points": [
                {"code": "SE-C7-01", "name": "记叙文阅读", "grade": 7},
                {"code": "SE-C7-02", "name": "文言文基础", "grade": 7},
            ],
            "tutorials": [
                {
                    "title": "记叙文六要素（公开教程）",
                    "unit_no": "1",
                    "lesson_title": "记叙文阅读",
                    "body_md": (
                        "# 记叙文六要素\n\n"
                        "时间、地点、人物、起因、经过、结果。\n"
                        "阅读时抓住线索与中心思想。\n"
                    ),
                }
            ],
            "questions": [
                {
                    "stem_md": "（公开样例）记叙文六要素不包括下列哪一项？",
                    "qtype": "single",
                    "options": ["时间", "地点", "修辞手法", "人物"],
                    "answer_md": "C",
                    "analysis_md": "修辞手法不属于六要素。",
                    "difficulty": 1,
                    "point_codes": ["SE-C7-01"],
                },
                {
                    "stem_md": "（公开样例）“之”在文言文中常作代词。判断对错。",
                    "qtype": "judge",
                    "answer_md": "对",
                    "analysis_md": "“之”可作代词，亦可作助词等，题干“常作代词”成立。",
                    "difficulty": 2,
                    "point_codes": ["SE-C7-02"],
                },
            ],
        }
    raise AppError(ErrorCode.NOT_FOUND, f"unknown fixture: {key}", status_code=404)


def fetch_feed_payload(*, feed_url: str, format_hint: str = "atrium_edu_json") -> dict[str, Any]:
    settings = get_settings()
    assert_url_allowed(feed_url)
    parsed = urlparse(feed_url)

    if parsed.scheme == "fixture":
        key = parsed.netloc or parsed.path.lstrip("/")
        return _fixture_payload(key)

    is_local = (parsed.hostname or "").lower() in {"127.0.0.1", "localhost"}
    if settings.edu_official_mode != "live" and not is_local:
        raise AppError(
            ErrorCode.FORBIDDEN,
            "live official fetch disabled; set EDU_OFFICIAL_MODE=live",
            status_code=403,
        )

    timeout = settings.edu_official_timeout_seconds
    headers = {"User-Agent": "AtriumKB-EduOfficialFetcher/1.0 (+licensed-open-feeds)"}
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            resp = client.get(feed_url)
            resp.raise_for_status()
            ctype = (resp.headers.get("content-type") or "").lower()
            text = resp.text
    except httpx.HTTPError as exc:
        raise AppError(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            f"failed to fetch official feed: {exc}",
            status_code=502,
        ) from exc

    if "json" in ctype or text.lstrip().startswith("{") or text.lstrip().startswith("["):
        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            raise AppError(ErrorCode.VALIDATION_ERROR, "feed is not valid JSON", status_code=400) from exc
        if isinstance(data, list):
            return {"questions": data, "pack": {}, "points": [], "tutorials": []}
        if not isinstance(data, dict):
            raise AppError(ErrorCode.VALIDATION_ERROR, "unexpected JSON feed shape", status_code=400)
        return data

    # Minimal HTML → tutorial extraction for allowlisted official pages.
    title_m = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.I | re.S)
    title = re.sub(r"\s+", " ", title_m.group(1)).strip() if title_m else "官方页面"
    cleaned = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    cleaned = re.sub(r"(?is)<br\s*/?>", "\n", cleaned)
    cleaned = re.sub(r"(?is)</p>", "\n\n", cleaned)
    cleaned = re.sub(r"(?is)<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if len(cleaned) < 40:
        raise AppError(ErrorCode.VALIDATION_ERROR, "HTML page has no extractable tutorial text", status_code=400)
    return {
        "pack": {
            "name": f"官网同步·{title[:80]}",
            "license_type": "open",
            "license_note": f"从允许域名页面抽取教程正文：{feed_url}",
        },
        "points": [],
        "tutorials": [
            {
                "title": title[:200],
                "unit_no": "",
                "lesson_title": title[:200],
                "body_md": cleaned[:20000],
            }
        ],
        "questions": [],
    }


def _import_tutorial_document(
    db: Session,
    *,
    tenant_id: str,
    workspace_id: str,
    user_id: str,
    pack_id: str,
    stage: str,
    subject: str,
    grade: int,
    edition: str,
    title: str,
    body_md: str,
    unit_no: str = "",
    lesson_title: str = "",
) -> str:
    doc = Document(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        title=title,
        status="indexed",
        created_by=user_id,
    )
    db.add(doc)
    db.flush()
    storage = get_storage()
    stored_key = f"{tenant_id}/{workspace_id}/{doc.id}/v1/official.md"
    raw = body_md.encode("utf-8")
    storage.put_bytes(stored_key, raw)
    version = DocumentVersion(
        tenant_id=tenant_id,
        document_id=doc.id,
        version_no=1,
        object_key=stored_key,
        content_type="text/markdown",
        size_bytes=len(raw),
        status="indexed",
    )
    db.add(version)
    db.flush()
    db.add(
        UploadJob(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            document_id=doc.id,
            version_id=version.id,
            filename=f"{title}.md",
            content_type="text/markdown",
            size_bytes=len(raw),
            object_key=stored_key,
            status="indexed",
            created_by=user_id,
        )
    )
    grant_default_acl(
        db,
        tenant_id=tenant_id,
        document_id=doc.id,
        user_id=user_id,
        workspace_id=workspace_id,
    )
    for i, content in enumerate(chunk_text(body_md)):
        tokens = tokenize(content)
        db.add(
            Chunk(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                document_id=doc.id,
                version_id=version.id,
                ordinal=i,
                content=content,
                token_count=len(tokens),
                embedding_json=json.dumps(embed_text(content)),
                status="active",
            )
        )
    db.flush()
    upsert_document_meta(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        document_id=doc.id,
        stage=stage,
        subject=subject,
        grade=grade,
        pack_id=pack_id,
        edition=edition,
        volume="",
        unit_no=unit_no,
        lesson_title=lesson_title or title,
        curriculum_code="",
    )
    return doc.id


def sync_official_source(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    workspace_id: str,
    source_id: str,
    accept_license: bool,
    feed_url: str | None = None,
    pack_id: str | None = None,
) -> SyncResult:
    require_edu_enabled()
    settings = get_settings()
    if not settings.edu_official_fetch_enabled:
        raise AppError(ErrorCode.FORBIDDEN, "official education fetch disabled", status_code=403)
    if not accept_license:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "accept_license=true is required to sync official education content",
            status_code=400,
        )

    ws = db.scalar(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.tenant_id == tenant_id,
            Workspace.status == "active",
        )
    )
    if ws is None:
        raise AppError(ErrorCode.NOT_FOUND, "workspace not found", status_code=404)

    source = get_source(source_id)
    url = (feed_url or source.feed_url or "").strip()
    if source_id == "live-custom" and not url:
        raise AppError(ErrorCode.VALIDATION_ERROR, "feed_url required for live-custom", status_code=400)
    if not url:
        raise AppError(ErrorCode.VALIDATION_ERROR, "source has empty feed_url", status_code=400)

    job = EduOfficialSyncJob(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        source_id=source.id,
        feed_url=url,
        status="running",
        created_by=user_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    result = SyncResult(job_id=job.id, source_id=source.id, pack_id="", status="running")
    try:
        payload = fetch_feed_payload(feed_url=url, format_hint=source.format)
        pack_meta = payload.get("pack") or {}
        stage = str(pack_meta.get("stage") or source.stage)
        subject = str(pack_meta.get("subject") or source.subject)
        grade = int(pack_meta.get("grade_min") or source.grade or 7)
        license_type = str(pack_meta.get("license_type") or source.license_type)
        license_note = str(pack_meta.get("license_note") or source.license_note)
        edition = str(pack_meta.get("edition") or source.provider)
        pack_name = str(pack_meta.get("name") or source.name)

        pack: EduContentPack | None = None
        if pack_id:
            pack = get_pack(db, tenant_id=tenant_id, pack_id=pack_id)
        else:
            # Reuse existing pack with same name for idempotent re-sync.
            for p in list_packs(db, tenant_id=tenant_id):
                if p.name == pack_name and p.subject == subject:
                    pack = p
                    break
        if pack is None:
            pack = create_pack(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                name=pack_name,
                stage=stage,
                subject=subject,
                license_type=license_type,
                license_note=license_note,
                edition=edition,
                grade_min=int(pack_meta.get("grade_min") or grade),
                grade_max=int(pack_meta.get("grade_max") or grade),
            )
        result.pack_id = pack.id

        code_to_id: dict[str, str] = {}
        for pt in payload.get("points") or []:
            point = upsert_point(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                name=str(pt.get("name") or "").strip(),
                code=str(pt.get("code") or "").strip(),
                subject=subject,
                stage=stage,
                grade=pt.get("grade") if pt.get("grade") is not None else grade,
                pack_id=pack.id,
            )
            if point.code:
                code_to_id[point.code] = point.id
            result.points_imported += 1

        for tut in payload.get("tutorials") or []:
            body = str(tut.get("body_md") or tut.get("content") or "").strip()
            title = str(tut.get("title") or "官方教程").strip()
            if not body:
                continue
            doc_id = _import_tutorial_document(
                db,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                user_id=user_id,
                pack_id=pack.id,
                stage=stage,
                subject=subject,
                grade=grade,
                edition=edition,
                title=title,
                body_md=body,
                unit_no=str(tut.get("unit_no") or ""),
                lesson_title=str(tut.get("lesson_title") or title),
            )
            result.document_ids.append(doc_id)
            result.tutorials_imported += 1

        for q in payload.get("questions") or []:
            stem = str(q.get("stem_md") or q.get("stem") or "").strip()
            if not stem:
                continue
            point_ids: list[str] = []
            for code in q.get("point_codes") or []:
                if code in code_to_id:
                    point_ids.append(code_to_id[code])
            for pid in q.get("knowledge_point_ids") or []:
                point_ids.append(str(pid))
            # Anchor first tutorial doc of this sync when available.
            anchors = []
            if result.document_ids:
                anchors.append({"document_id": result.document_ids[0], "note": "official sync"})
            created = create_question(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                stem_md=stem,
                qtype=str(q.get("qtype") or "essay"),
                subject=subject,
                stage=stage,
                answer_md=str(q.get("answer_md") or q.get("answer") or ""),
                analysis_md=str(q.get("analysis_md") or q.get("analysis") or ""),
                options=list(q.get("options") or []),
                difficulty=int(q.get("difficulty") or 3),
                grade=int(q.get("grade") or grade),
                pack_id=pack.id,
                source_doc_id=result.document_ids[0] if result.document_ids else None,
                knowledge_point_ids=point_ids,
                anchors=anchors,
            )
            result.question_ids.append(created.id)
            result.questions_imported += 1

        result.status = "succeeded"
        job.status = "succeeded"
        job.pack_id = pack.id
        job.tutorials_imported = result.tutorials_imported
        job.questions_imported = result.questions_imported
        job.points_imported = result.points_imported
        job.detail_json = json.dumps(
            {
                "document_ids": result.document_ids,
                "question_ids": result.question_ids,
                "feed_url": url,
            },
            ensure_ascii=False,
        )
        job.finished_at = datetime.now(UTC)
        db.add(
            AuditEvent(
                tenant_id=tenant_id,
                actor_id=user_id,
                action="edu.official.sync",
                resource_type="edu_content_pack",
                resource_id=pack.id,
                detail=json.dumps(
                    {
                        "source_id": source.id,
                        "tutorials": result.tutorials_imported,
                        "questions": result.questions_imported,
                        "points": result.points_imported,
                    },
                    ensure_ascii=False,
                ),
            )
        )
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        job = db.get(EduOfficialSyncJob, result.job_id)
        if job:
            job.status = "failed"
            job.error = str(exc)
            job.finished_at = datetime.now(UTC)
            db.commit()
        if isinstance(exc, AppError):
            raise
        raise AppError(ErrorCode.INTERNAL_ERROR, f"official sync failed: {exc}", status_code=500) from exc

    return result
