from pathlib import Path

from fastapi.testclient import TestClient

from shared.config import get_settings
from shared.db import init_db, reset_engine


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'e2.db'}")
    monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long!!")
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(tmp_path / "objects"))
    monkeypatch.setenv("PROFILE", "personal")
    get_settings.cache_clear()
    reset_engine()
    init_db()
    from api.main import app

    return TestClient(app)


def _register(client: TestClient, slug: str, email: str) -> dict:
    resp = client.post(
        "/v1/auth/register",
        json={
            "tenant_name": slug,
            "tenant_slug": slug,
            "email": email,
            "password": "password123",
            "display_name": slug,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_upload_flow_and_idempotency(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    reg = _register(client, "acme", "admin@acme.example")
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    ws = client.get("/v1/workspaces", headers=headers).json()[0]

    p1 = client.post(
        "/v1/uploads/presign",
        headers=headers,
        json={
            "workspace_id": ws["id"],
            "filename": "note.md",
            "content_type": "text/markdown",
            "idempotency_key": "idem-1",
        },
    )
    assert p1.status_code == 200, p1.text
    job_id = p1.json()["upload_job_id"]

    p2 = client.post(
        "/v1/uploads/presign",
        headers=headers,
        json={
            "workspace_id": ws["id"],
            "filename": "note.md",
            "content_type": "text/markdown",
            "idempotency_key": "idem-1",
        },
    )
    assert p2.json()["upload_job_id"] == job_id

    content = b"# hello knowledge\n"
    up = client.put(
        f"/v1/upload-jobs/{job_id}/content",
        headers=headers,
        files={"file": ("note.md", content, "text/markdown")},
    )
    assert up.status_code == 200, up.text
    assert up.json()["status"] == "uploaded"
    assert up.json()["size_bytes"] == len(content)

    done = client.post(f"/v1/upload-jobs/{job_id}/complete", headers=headers)
    assert done.status_code == 200
    # Personal profile completes then runs ingest inline (E3).
    assert done.json()["status"] == "indexed"

    got = client.get(f"/v1/upload-jobs/{job_id}", headers=headers)
    assert got.status_code == 200
    assert got.json()["status"] == "indexed"


def test_upload_job_cross_tenant_hidden(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    a = _register(client, "alpha", "a@alpha.example")
    b = _register(client, "beta", "b@beta.example")
    ha = {"Authorization": f"Bearer {a['access_token']}"}
    hb = {"Authorization": f"Bearer {b['access_token']}"}
    ws = client.get("/v1/workspaces", headers=ha).json()[0]

    presign = client.post(
        "/v1/uploads/presign",
        headers=ha,
        json={"workspace_id": ws["id"], "filename": "secret.md"},
    )
    job_id = presign.json()["upload_job_id"]
    client.put(
        f"/v1/upload-jobs/{job_id}/content",
        headers=ha,
        files={"file": ("secret.md", b"secret", "text/markdown")},
    )

    denied = client.get(f"/v1/upload-jobs/{job_id}", headers=hb)
    assert denied.status_code == 404
