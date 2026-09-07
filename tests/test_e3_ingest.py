from pathlib import Path

from fastapi.testclient import TestClient
from shared.config import get_settings
from shared.db import get_session_factory, init_db, reset_engine
from shared.db.models import AuditEvent, Chunk, DocumentAcl
from shared.ingest import chunk_text, cosine, embed_text
from sqlalchemy import select


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'e3.db'}")
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


def test_chunk_and_embed_deterministic():
    pieces = chunk_text("Alpha\n\n" + ("word " * 200))
    assert len(pieces) >= 2
    a = embed_text("knowledge base embeddings")
    b = embed_text("knowledge base embeddings")
    c = embed_text("completely unrelated zebra")
    assert a == b
    assert cosine(a, b) > 0.99
    assert cosine(a, c) < cosine(a, b)


def test_upload_indexes_chunks_and_acl(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    reg = _register(client, "acme", "admin@acme.example")
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    ws = client.get("/v1/workspaces", headers=headers).json()[0]

    body = (
        "# Personal KB\n\n"
        "The unique phrase xylophone-quantum-lattice appears here.\n\n"
        + ("More context paragraph.\n\n" * 5)
    ).encode()

    presign = client.post(
        "/v1/uploads/presign",
        headers=headers,
        json={
            "workspace_id": ws["id"],
            "filename": "note.md",
            "content_type": "text/markdown",
        },
    )
    assert presign.status_code == 200, presign.text
    job_id = presign.json()["upload_job_id"]
    document_id = presign.json()["document_id"]

    up = client.put(
        f"/v1/upload-jobs/{job_id}/content",
        headers=headers,
        files={"file": ("note.md", body, "text/markdown")},
    )
    assert up.status_code == 200

    done = client.post(f"/v1/upload-jobs/{job_id}/complete", headers=headers)
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "indexed"

    doc = client.get(f"/v1/documents/{document_id}", headers=headers)
    assert doc.status_code == 200
    assert doc.json()["status"] in {"indexed", "published", "learned"}
    assert doc.json()["chunk_count"] >= 1

    session = get_session_factory()()
    chunks = session.scalars(
        select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.ordinal)
    ).all()
    assert len(chunks) >= 1
    assert chunks[0].tenant_id == reg["tenant_id"]
    assert chunks[0].embedding_json.startswith("[")
    acls = session.scalars(select(DocumentAcl).where(DocumentAcl.document_id == document_id)).all()
    assert any(a.principal_type == "user" and a.principal_id == reg["user_id"] for a in acls)
    assert any(a.principal_type == "workspace" and a.principal_id == ws["id"] for a in acls)
    audits = session.scalars(
        select(AuditEvent).where(
            AuditEvent.tenant_id == reg["tenant_id"],
            AuditEvent.action.in_(["upload.completed", "document.indexed"]),
        )
    ).all()
    actions = {a.action for a in audits}
    assert "upload.completed" in actions
    assert "document.indexed" in actions
    session.close()

    # Idempotent re-process keeps a single set of chunks
    again = client.post(f"/v1/upload-jobs/{job_id}/process", headers=headers)
    assert again.status_code == 200
    assert again.json()["status"] == "indexed"
    session = get_session_factory()()
    chunks2 = session.scalars(select(Chunk).where(Chunk.document_id == document_id)).all()
    assert len(chunks2) == len(chunks)
    session.close()
