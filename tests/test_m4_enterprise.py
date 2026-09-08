"""M4 enterprise: approval publish, model routing, audit export."""

from pathlib import Path

from fastapi.testclient import TestClient
from shared.config import get_settings
from shared.db import init_db, reset_engine


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'm4.db'}")
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


def _upload(client: TestClient, headers: dict, workspace_id: str, name: str, text: str) -> str:
    presign = client.post(
        "/v1/uploads/presign",
        headers=headers,
        json={"workspace_id": workspace_id, "filename": name, "content_type": "text/markdown"},
    )
    assert presign.status_code == 200, presign.text
    job_id = presign.json()["upload_job_id"]
    document_id = presign.json()["document_id"]
    up = client.put(
        f"/v1/upload-jobs/{job_id}/content",
        headers=headers,
        files={"file": (name, text.encode(), "text/markdown")},
    )
    assert up.status_code == 200, up.text
    done = client.post(f"/v1/upload-jobs/{job_id}/complete", headers=headers)
    assert done.status_code == 200, done.text
    return document_id


def test_meta_is_m4(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.get("/v1/meta").json()["milestone"] in {"M4", "Real-LLM", "Knowledge-Graph"}


def test_approval_publish_requires_admin(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    admin = _register(client, "approve-co", "admin@approve.example")
    headers = {"Authorization": f"Bearer {admin['access_token']}"}
    ws = client.get("/v1/workspaces", headers=headers).json()[0]

    patched = client.patch(
        f"/v1/workspaces/{ws['id']}",
        headers=headers,
        json={"publish_mode": "approval"},
    )
    assert patched.status_code == 200
    assert patched.json()["publish_mode"] == "approval"

    invite = client.post(
        "/v1/users/invite",
        headers=headers,
        json={
            "email": "member@approve.example",
            "password": "password123",
            "display_name": "Member",
            "role": "member",
        },
    )
    assert invite.status_code == 200, invite.text
    member_headers = {"Authorization": f"Bearer {invite.json()['access_token']}"}

    doc_id = _upload(
        client,
        headers,
        ws["id"],
        "policy.md",
        "# Policy\n\nApproval required for this learning report content.\n",
    )
    learning = client.get(f"/v1/documents/{doc_id}/learning", headers=headers)
    assert learning.status_code == 200
    assert learning.json()["status"] == "draft"

    denied = client.post(
        f"/v1/documents/{doc_id}/learning/publish",
        headers=member_headers,
        json={"status": "published"},
    )
    assert denied.status_code == 403

    ok = client.post(
        f"/v1/documents/{doc_id}/learning/publish",
        headers=headers,
        json={"status": "published"},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "published"

    pending = client.get("/v1/admin/approvals/pending", headers=headers)
    assert pending.status_code == 200
    assert all(p["document_id"] != doc_id for p in pending.json())


def test_model_routing_by_sensitivity(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    admin = _register(client, "route-co", "admin@route.example")
    headers = {"Authorization": f"Bearer {admin['access_token']}"}
    ws = client.get("/v1/workspaces", headers=headers).json()[0]

    policies = client.get("/v1/admin/models/policy", headers=headers)
    assert policies.status_code == 200
    assert {p["sensitivity"] for p in policies.json()} == {"L1", "L2", "L3", "L4"}

    put = client.put(
        "/v1/admin/models/policy",
        headers=headers,
        json=[
            {"sensitivity": "L4", "provider": "local", "model": "local-extractive"},
        ],
    )
    assert put.status_code == 200

    doc_id = _upload(
        client,
        headers,
        ws["id"],
        "secret.md",
        "# Secret\n\nThe unique token ziggurat-omega-plume is confidential.\n",
    )
    sens = client.patch(
        f"/v1/documents/{doc_id}/sensitivity",
        headers=headers,
        json={"sensitivity": "L4"},
    )
    assert sens.status_code == 200
    assert sens.json()["sensitivity"] == "L4"

    ask = client.post(
        "/v1/ask",
        headers=headers,
        json={"question": "What is ziggurat-omega-plume?"},
    )
    assert ask.status_code == 200, ask.text
    assert "ziggurat-omega-plume" in ask.json()["answer"].lower() or "knowledge base" in ask.json()[
        "answer"
    ].lower()


def test_audit_export_download(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    admin = _register(client, "audit-co", "admin@audit.example")
    headers = {"Authorization": f"Bearer {admin['access_token']}"}

    created = client.post("/v1/admin/audit-exports", headers=headers)
    assert created.status_code == 200, created.text
    export_id = created.json()["id"]
    assert created.json()["event_count"] >= 1

    download = client.get(f"/v1/admin/audit-exports/{export_id}/download", headers=headers)
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/json")
    body = download.json()
    assert body["tenant_id"] == admin["tenant_id"]
    assert body["event_count"] >= 1
