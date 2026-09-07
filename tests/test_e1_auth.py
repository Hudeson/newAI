from pathlib import Path

from fastapi.testclient import TestClient
from shared.config import get_settings
from shared.db import init_db, reset_engine


def _fresh(tmp_path: Path, monkeypatch) -> TestClient:
    db_path = tmp_path / "e1.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("PROFILE", "personal")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    get_settings.cache_clear()
    reset_engine()
    init_db()
    from api.main import app

    return TestClient(app)


def _register(client: TestClient, slug: str, email: str) -> dict:
    resp = client.post(
        "/v1/auth/register",
        json={
            "tenant_name": slug.upper(),
            "tenant_slug": slug,
            "email": email,
            "password": "password123",
            "display_name": email.split("@")[0],
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_register_login_me(tmp_path: Path, monkeypatch):
    client = _fresh(tmp_path, monkeypatch)
    reg = _register(client, "acme", "admin@acme.example")
    headers = {"Authorization": f"Bearer {reg['access_token']}"}

    me = client.get("/v1/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == "admin@acme.example"
    assert me.json()["role"] == "admin"
    assert me.json()["tenant_id"] == reg["tenant_id"]

    login = client.post(
        "/v1/auth/login",
        json={
            "tenant_slug": "acme",
            "email": "admin@acme.example",
            "password": "password123",
        },
    )
    assert login.status_code == 200
    assert login.json()["tenant_id"] == reg["tenant_id"]


def test_workspaces_tenant_scoped(tmp_path: Path, monkeypatch):
    client = _fresh(tmp_path, monkeypatch)
    a = _register(client, "tenant-a", "a@tenant-a.example")
    b = _register(client, "tenant-b", "b@tenant-b.example")
    ha = {"Authorization": f"Bearer {a['access_token']}"}
    hb = {"Authorization": f"Bearer {b['access_token']}"}

    created = client.post(
        "/v1/workspaces",
        headers=ha,
        json={"name": "Research", "slug": "research", "publish_mode": "auto"},
    )
    assert created.status_code == 200
    assert created.json()["tenant_id"] == a["tenant_id"]

    list_a = client.get("/v1/workspaces", headers=ha)
    list_b = client.get("/v1/workspaces", headers=hb)
    assert list_a.status_code == 200
    assert list_b.status_code == 200
    slugs_a = {w["slug"] for w in list_a.json()}
    slugs_b = {w["slug"] for w in list_b.json()}
    assert "research" in slugs_a
    assert "default" in slugs_a
    assert "research" not in slugs_b
    assert slugs_b == {"default"}


def test_me_requires_auth(tmp_path: Path, monkeypatch):
    client = _fresh(tmp_path, monkeypatch)
    resp = client.get("/v1/me")
    assert resp.status_code == 401


def test_cross_tenant_token_cannot_see_other_workspace_ids(tmp_path: Path, monkeypatch):
    client = _fresh(tmp_path, monkeypatch)
    a = _register(client, "alpha", "a@alpha.example")
    b = _register(client, "beta", "b@beta.example")
    ha = {"Authorization": f"Bearer {a['access_token']}"}
    hb = {"Authorization": f"Bearer {b['access_token']}"}

    wa = client.get("/v1/workspaces", headers=ha).json()
    wb = client.get("/v1/workspaces", headers=hb).json()
    assert {x["tenant_id"] for x in wa} == {a["tenant_id"]}
    assert {x["tenant_id"] for x in wb} == {b["tenant_id"]}
    assert a["tenant_id"] != b["tenant_id"]
