from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from shared.config import get_settings
from shared.db import init_db, reset_engine
from shared.edu_official import assert_url_allowed, fetch_feed_payload
from shared.errors import AppError


def _client(tmp_path: Path, monkeypatch, **env) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'edu-off.db'}")
    monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long!!")
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(tmp_path / "objects"))
    monkeypatch.setenv("PROFILE", "personal")
    monkeypatch.setenv("LLM_PROVIDER", "local")
    monkeypatch.setenv("EDU_ENABLED", "true")
    monkeypatch.setenv("EDU_OFFICIAL_FETCH_ENABLED", "true")
    monkeypatch.setenv("EDU_OFFICIAL_MODE", env.get("EDU_OFFICIAL_MODE", "fixture"))
    if "EDU_OFFICIAL_ALLOW_HOSTS" in env:
        monkeypatch.setenv("EDU_OFFICIAL_ALLOW_HOSTS", env["EDU_OFFICIAL_ALLOW_HOSTS"])
    get_settings.cache_clear()
    reset_engine()
    init_db()
    from api.main import app

    return TestClient(app)


def _register(client: TestClient, slug: str) -> dict:
    resp = client.post(
        "/v1/auth/register",
        json={
            "tenant_name": slug,
            "tenant_slug": slug,
            "email": f"admin@{slug}.example",
            "password": "password123",
            "display_name": slug,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_allowlist_blocks_unknown_host(monkeypatch):
    monkeypatch.setenv("EDU_OFFICIAL_ALLOW_HOSTS", "")
    get_settings.cache_clear()
    try:
        assert_url_allowed("https://evil-exam-bank.example/steal")
        assert False, "expected AppError"
    except AppError as exc:
        assert exc.status_code == 403


def test_fixture_payload_math():
    data = fetch_feed_payload(feed_url="fixture://moe-math-g7")
    assert data["pack"]["subject"] == "math"
    assert len(data["questions"]) >= 3
    assert len(data["tutorials"]) >= 1


def test_list_sources_and_sync_fixture(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    reg = _register(client, "off1")
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    ws = client.get("/v1/workspaces", headers=headers).json()[0]["id"]

    sources = client.get("/v1/edu/official/sources", headers=headers)
    assert sources.status_code == 200
    ids = {s["id"] for s in sources.json()}
    assert "fixture-moe-math-g7" in ids

    denied = client.post(
        "/v1/edu/official/sync",
        headers=headers,
        json={
            "source_id": "fixture-moe-math-g7",
            "workspace_id": ws,
            "accept_license": False,
        },
    )
    assert denied.status_code == 400

    synced = client.post(
        "/v1/edu/official/sync",
        headers=headers,
        json={
            "source_id": "fixture-moe-math-g7",
            "workspace_id": ws,
            "accept_license": True,
        },
    )
    assert synced.status_code == 200, synced.text
    body = synced.json()
    assert body["status"] == "succeeded"
    assert body["questions_imported"] >= 3
    assert body["tutorials_imported"] >= 1
    assert body["points_imported"] >= 2

    packs = client.get("/v1/edu/packs", headers=headers).json()
    assert any(p["license_type"] == "open" for p in packs)

    questions = client.get("/v1/edu/questions", headers=headers, params={"subject": "math"})
    assert questions.status_code == 200
    assert len(questions.json()) >= 3

    docs = client.get("/v1/documents", headers=headers, params={"workspace_id": ws})
    assert docs.status_code == 200
    assert len(docs.json()) >= 1

    job = client.get(f"/v1/edu/official/sync/{body['job_id']}", headers=headers)
    assert job.status_code == 200
    assert job.json()["status"] == "succeeded"


def test_live_custom_json_from_localhost(tmp_path: Path, monkeypatch):
    payload = {
        "pack": {
            "name": "本地授权 JSON 源",
            "stage": "junior",
            "subject": "math",
            "grade_min": 7,
            "grade_max": 7,
            "license_type": "licensed",
            "license_note": "测试授权",
            "edition": "local-test",
        },
        "points": [{"code": "L-1", "name": "测试知识点", "grade": 7}],
        "tutorials": [
            {
                "title": "本地教程",
                "body_md": "# 本地教程\n\n这是一段足够长的官方授权教程正文，用于验证自动拉取与入库。\n",
            }
        ],
        "questions": [
            {
                "stem_md": "1+1=？",
                "qtype": "fill",
                "answer_md": "2",
                "analysis_md": "基础运算",
                "difficulty": 1,
                "point_codes": ["L-1"],
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    class PatchedClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("shared.edu_official.httpx.Client", PatchedClient)

    client = _client(tmp_path, monkeypatch, EDU_OFFICIAL_MODE="live")
    reg = _register(client, "off2")
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    ws = client.get("/v1/workspaces", headers=headers).json()[0]["id"]

    synced = client.post(
        "/v1/edu/official/sync",
        headers=headers,
        json={
            "source_id": "live-custom",
            "workspace_id": ws,
            "accept_license": True,
            "feed_url": "http://127.0.0.1:9/official-feed.json",
        },
    )
    assert synced.status_code == 200, synced.text
    assert synced.json()["questions_imported"] == 1
    assert synced.json()["tutorials_imported"] == 1
    _ = real_client


def test_chinese_fixture_sync(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    reg = _register(client, "off3")
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    ws = client.get("/v1/workspaces", headers=headers).json()[0]["id"]
    synced = client.post(
        "/v1/edu/official/sync",
        headers=headers,
        json={
            "source_id": "fixture-smartedu-chinese-g7",
            "workspace_id": ws,
            "accept_license": True,
        },
    )
    assert synced.status_code == 200, synced.text
    qs = client.get("/v1/edu/questions", headers=headers, params={"subject": "chinese"}).json()
    assert len(qs) >= 2
