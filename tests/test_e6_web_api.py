from pathlib import Path

from fastapi.testclient import TestClient

from shared.config import get_settings
from shared.db import init_db, reset_engine


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'e6.db'}")
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


def test_list_users_and_documents_for_web(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    admin = _register(client, "webco", "admin@webco.example")
    headers = {"Authorization": f"Bearer {admin['access_token']}"}

    users = client.get("/v1/users", headers=headers)
    assert users.status_code == 200, users.text
    assert len(users.json()) == 1
    assert users.json()[0]["email"] == "admin@webco.example"

    ws = client.get("/v1/workspaces", headers=headers).json()[0]
    docs_empty = client.get(f"/v1/documents?workspace_id={ws['id']}", headers=headers)
    assert docs_empty.status_code == 200
    assert docs_empty.json() == []

    # upload one doc so library can list it
    content = b"# Web Doc\n\nAtrium frontend listing probe.\n"
    presign = client.post(
        "/v1/uploads/presign",
        headers=headers,
        json={
            "workspace_id": ws["id"],
            "filename": "web.md",
            "content_type": "text/markdown",
        },
    )
    assert presign.status_code == 200, presign.text
    job_id = presign.json()["upload_job_id"]
    client.put(
        f"/v1/upload-jobs/{job_id}/content",
        headers=headers,
        files={"file": ("web.md", content, "text/markdown")},
    )
    done = client.post(f"/v1/upload-jobs/{job_id}/complete", headers=headers)
    assert done.status_code == 200
    assert done.json()["status"] == "indexed"

    docs = client.get(f"/v1/documents?workspace_id={ws['id']}", headers=headers)
    assert docs.status_code == 200
    assert len(docs.json()) == 1
    assert docs.json()[0]["chunk_count"] >= 1

    meta = client.get("/v1/meta")
    assert meta.json()["milestone"] in {"E6", "E7"}


def test_cors_allows_web_origin(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.options(
        "/v1/meta",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code in {200, 204}
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
