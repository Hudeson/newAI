from pathlib import Path

from fastapi.testclient import TestClient
from shared.config import get_settings
from shared.db import get_session_factory, init_db, reset_engine
from sqlalchemy import select


def _fresh_db(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("PROFILE", "personal")
    get_settings.cache_clear()
    reset_engine()
    init_db()


def test_healthz(tmp_path: Path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    from api.main import app

    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "X-Request-Id" in resp.headers


def test_readyz_and_meta(tmp_path: Path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    from api.main import app

    client = TestClient(app)
    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["checks"]["database"] is True

    meta = client.get("/v1/meta")
    assert meta.status_code == 200
    assert meta.json()["milestone"] in {
    "E0",
    "E1",
    "E2",
    "E3",
    "E4",
    "E5",
    "E6",
    "E7",
    "M4",
    "Real-LLM",
    "Knowledge-Graph",
}
    assert meta.json()["request_id"]


def test_request_id_echo(tmp_path: Path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    from api.main import app

    client = TestClient(app)
    resp = client.get("/healthz", headers={"X-Request-Id": "fixed-req-1"})
    assert resp.headers["X-Request-Id"] == "fixed-req-1"


def test_tenant_workspace_models(tmp_path: Path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    from shared.db.models import Tenant, User, Workspace

    session = get_session_factory()()
    tenant = Tenant(name="Acme", slug="acme")
    session.add(tenant)
    session.flush()
    session.add_all(
        [
            User(tenant_id=tenant.id, email="a@acme.test", display_name="A", role="admin"),
            Workspace(tenant_id=tenant.id, name="Default", slug="default"),
        ]
    )
    session.commit()
    users = session.scalars(select(User).where(User.tenant_id == tenant.id)).all()
    assert len(users) == 1
    session.close()
