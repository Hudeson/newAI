from pathlib import Path

from fastapi.testclient import TestClient
from shared.config import get_settings
from shared.db import init_db, reset_engine
from shared.web_search import filter_allowlisted, web_search, WebHit


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'web.db'}")
    monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long!!")
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(tmp_path / "objects"))
    monkeypatch.setenv("PROFILE", "personal")
    monkeypatch.setenv("LLM_PROVIDER", "local")
    monkeypatch.setenv("EDU_ENABLED", "true")
    monkeypatch.setenv("WEB_SEARCH_ENABLED", "true")
    monkeypatch.setenv("WEB_SEARCH_MODE", "fixture")
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "fixture")
    monkeypatch.setenv("EDU_WEB_SEARCH_ENABLED", "true")
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


def test_fixture_web_search_math():
    hits = web_search("七年级有理数 课标", limit=5, education=True)
    assert hits
    assert any(h.url.startswith("fixture://") for h in hits)


def test_filter_allowlisted_keeps_fixture_and_moe():
    hits = [
        WebHit("a", "fixture://moe-math-g7", "x", "fixture", 1.0),
        WebHit("b", "https://www.moe.gov.cn/x", "y", "x", 0.5),
        WebHit("c", "https://evil.example/z", "z", "x", 0.4),
    ]
    kept = filter_allowlisted(hits)
    urls = {h.url for h in kept}
    assert "fixture://moe-math-g7" in urls
    assert "https://www.moe.gov.cn/x" in urls
    assert "https://evil.example/z" not in urls


def test_edu_web_search_auto_import(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    reg = _register(client, "web1")
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    ws = client.get("/v1/workspaces", headers=headers).json()[0]["id"]

    denied = client.post(
        "/v1/edu/web-search",
        headers=headers,
        json={
            "query": "初中数学有理数",
            "workspace_id": ws,
            "auto_import": True,
            "accept_license": False,
        },
    )
    assert denied.status_code == 400

    ok = client.post(
        "/v1/edu/web-search",
        headers=headers,
        json={
            "query": "初中数学有理数",
            "workspace_id": ws,
            "subject": "math",
            "stage": "junior",
            "grade": 7,
            "auto_import": True,
            "accept_license": True,
            "limit": 5,
        },
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["hits"]
    assert body["imports"]
    assert body["imports"][0]["questions_imported"] >= 1

    qs = client.get("/v1/edu/questions", headers=headers, params={"subject": "math"})
    assert qs.status_code == 200
    assert len(qs.json()) >= 1


def test_ask_web_search_augment(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    reg = _register(client, "web2")
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    resp = client.post(
        "/v1/ask",
        headers=headers,
        json={"question": "有理数运算法则是什么？", "web_search": True, "limit": 3},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["web_search_augmented"] is True
    assert data["web_citations"]
    assert data["answer"]
