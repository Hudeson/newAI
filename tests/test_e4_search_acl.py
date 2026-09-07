import inspect
from pathlib import Path

from fastapi.testclient import TestClient
from shared.config import get_settings
from shared.db import init_db, reset_engine
from shared.search import search_chunks


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'e4.db'}")
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


def _upload_indexed(
    client: TestClient,
    headers: dict,
    workspace_id: str,
    filename: str,
    text: str,
) -> dict:
    presign = client.post(
        "/v1/uploads/presign",
        headers=headers,
        json={"workspace_id": workspace_id, "filename": filename, "content_type": "text/markdown"},
    )
    assert presign.status_code == 200, presign.text
    job_id = presign.json()["upload_job_id"]
    document_id = presign.json()["document_id"]
    content = text.encode()
    up = client.put(
        f"/v1/upload-jobs/{job_id}/content",
        headers=headers,
        files={"file": (filename, content, "text/markdown")},
    )
    assert up.status_code == 200
    done = client.post(f"/v1/upload-jobs/{job_id}/complete", headers=headers)
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "indexed"
    return {"job_id": job_id, "document_id": document_id}


def test_search_requires_tenant_and_user_params():
    sig = inspect.signature(search_chunks)
    assert "tenant_id" in sig.parameters
    assert "user_id" in sig.parameters
    # Production search path must not allow unconstrained collection scroll.
    src = inspect.getsource(search_chunks)
    assert "tenant_id" in src
    assert "Chunk.tenant_id == tenant_id" in src
    assert "readable_document_ids" in src


def test_dual_tenant_search_isolation(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    a = _register(client, "alpha", "a@alpha.example")
    b = _register(client, "beta", "b@beta.example")
    ha = {"Authorization": f"Bearer {a['access_token']}"}
    hb = {"Authorization": f"Bearer {b['access_token']}"}
    ws_a = client.get("/v1/workspaces", headers=ha).json()[0]

    secret_phrase = "umbravex-midnight-orchid-protocol"
    uploaded = _upload_indexed(
        client,
        ha,
        ws_a["id"],
        "secret.md",
        f"# Secret Doc\n\nOnly tenant A owns {secret_phrase}.\n",
    )

    # T1: tenant A job ready / indexed
    job = client.get(f"/v1/upload-jobs/{uploaded['job_id']}", headers=ha)
    assert job.json()["status"] == "indexed"

    # Owner can search own phrase
    search_a = client.post("/v1/search", headers=ha, json={"query": secret_phrase, "limit": 5})
    assert search_a.status_code == 200, search_a.text
    assert len(search_a.json()["hits"]) >= 1
    assert any(secret_phrase.split("-")[0] in h["content"] for h in search_a.json()["hits"])

    # T2: tenant B search unique phrase → 0 hits
    search_b = client.post("/v1/search", headers=hb, json={"query": secret_phrase, "limit": 5})
    assert search_b.status_code == 200
    assert search_b.json()["hits"] == []

    # T3: tenant B GET A's document → 404
    denied = client.get(f"/v1/documents/{uploaded['document_id']}", headers=hb)
    assert denied.status_code == 404

    # T5: cross-tenant upload-job access still 404
    denied_job = client.get(f"/v1/upload-jobs/{uploaded['job_id']}", headers=hb)
    assert denied_job.status_code == 404


def test_acl_viewer_and_private_document(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    admin = _register(client, "gamma", "admin@gamma.example")
    ha = {"Authorization": f"Bearer {admin['access_token']}"}
    ws = client.get("/v1/workspaces", headers=ha).json()[0]

    invite = client.post(
        "/v1/users/invite",
        headers=ha,
        json={
            "email": "viewer@gamma.example",
            "password": "password123",
            "display_name": "Viewer",
            "role": "viewer",
        },
    )
    assert invite.status_code == 200, invite.text
    hv = {"Authorization": f"Bearer {invite.json()['access_token']}"}

    shared = _upload_indexed(
        client,
        ha,
        ws["id"],
        "shared.md",
        "# Shared\n\nWorkspace members can read shared-nebula-token.\n",
    )
    # T4: viewer (workspace member via default ACL) can read + search
    got = client.get(f"/v1/documents/{shared['document_id']}", headers=hv)
    assert got.status_code == 200
    search_v = client.post(
        "/v1/search", headers=hv, json={"query": "shared-nebula-token", "limit": 5}
    )
    assert search_v.status_code == 200
    assert len(search_v.json()["hits"]) >= 1

    private = _upload_indexed(
        client,
        ha,
        ws["id"],
        "private.md",
        "# Private\n\nOwner-only phrase zircon-cipher-vault.\n",
    )
    # Restrict ACL to owner only (no workspace grant)
    acl = client.put(
        f"/v1/documents/{private['document_id']}/acl",
        headers=ha,
        json={
            "entries": [
                {
                    "principal_type": "user",
                    "principal_id": admin["user_id"],
                    "permission": "read",
                },
                {
                    "principal_type": "user",
                    "principal_id": admin["user_id"],
                    "permission": "write",
                },
            ]
        },
    )
    assert acl.status_code == 200, acl.text

    # Non-member / no ACL → 404; private doc must not appear in search
    denied = client.get(f"/v1/documents/{private['document_id']}", headers=hv)
    assert denied.status_code == 404
    search_priv = client.post(
        "/v1/search", headers=hv, json={"query": "zircon-cipher-vault", "limit": 5}
    )
    assert search_priv.status_code == 200
    priv_hits = search_priv.json()["hits"]
    assert all(h["document_id"] != private["document_id"] for h in priv_hits)
    assert all("zircon-cipher-vault" not in h["content"] for h in priv_hits)
    assert priv_hits == []

    # Owner still sees private doc
    owner_doc = client.get(f"/v1/documents/{private['document_id']}", headers=ha)
    assert owner_doc.status_code == 200
    owner_search = client.post(
        "/v1/search", headers=ha, json={"query": "zircon-cipher-vault", "limit": 5}
    )
    assert len(owner_search.json()["hits"]) >= 1
    assert any(h["document_id"] == private["document_id"] for h in owner_search.json()["hits"])
