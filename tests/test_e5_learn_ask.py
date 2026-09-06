import inspect
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from shared.ask import validate_citations
from shared.config import get_settings
from shared.db import get_session_factory, init_db, reset_engine
from shared.db.models import LearningReport, UsageLedger


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'e5.db'}")
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


def _upload_indexed(client: TestClient, headers: dict, workspace_id: str, filename: str, text: str) -> dict:
    presign = client.post(
        "/v1/uploads/presign",
        headers=headers,
        json={"workspace_id": workspace_id, "filename": filename, "content_type": "text/markdown"},
    )
    assert presign.status_code == 200, presign.text
    job_id = presign.json()["upload_job_id"]
    document_id = presign.json()["document_id"]
    up = client.put(
        f"/v1/upload-jobs/{job_id}/content",
        headers=headers,
        files={"file": (filename, text.encode(), "text/markdown")},
    )
    assert up.status_code == 200, up.text
    done = client.post(f"/v1/upload-jobs/{job_id}/complete", headers=headers)
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "indexed"
    return {"job_id": job_id, "document_id": document_id}


def test_learn_report_auto_published_after_ingest(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    reg = _register(client, "learnco", "admin@learnco.example")
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    ws = client.get("/v1/workspaces", headers=headers).json()[0]

    body = (
        "# Quantum Notes\n\n"
        "The rare token nebulon-cascade-helix is the core idea.\n\n"
        "## Outline A\n\n"
        "Supporting detail about retrieval and citations.\n\n"
        "## Outline B\n\n"
        "Another paragraph with actionable key points for learners.\n"
    )
    uploaded = _upload_indexed(client, headers, ws["id"], "quantum.md", body)

    learning = client.get(f"/v1/documents/{uploaded['document_id']}/learning", headers=headers)
    assert learning.status_code == 200, learning.text
    payload = learning.json()
    assert payload["status"] == "published"
    assert "nebulon-cascade-helix" in payload["summary"] or any(
        "nebulon" in p for p in payload["key_points"]
    )
    assert len(payload["outline"]) >= 1

    session = get_session_factory()()
    reports = session.scalars(
        select(LearningReport).where(LearningReport.document_id == uploaded["document_id"])
    ).all()
    assert len(reports) == 1
    usage = session.scalars(
        select(UsageLedger).where(
            UsageLedger.tenant_id == reg["tenant_id"],
            UsageLedger.operation == "learn",
        )
    ).all()
    assert len(usage) >= 1
    session.close()


def test_ask_returns_authorized_citations_only(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    a = _register(client, "ask-a", "a@ask.example")
    b = _register(client, "ask-b", "b@ask.example")
    ha = {"Authorization": f"Bearer {a['access_token']}"}
    hb = {"Authorization": f"Bearer {b['access_token']}"}
    ws = client.get("/v1/workspaces", headers=ha).json()[0]

    phrase = "zirconium-lattice-oracle"
    uploaded = _upload_indexed(
        client,
        ha,
        ws["id"],
        "oracle.md",
        f"# Oracle\n\nOnly tenant A knows about {phrase}.\n",
    )

    ask_a = client.post("/v1/ask", headers=ha, json={"question": phrase, "limit": 5})
    assert ask_a.status_code == 200, ask_a.text
    body = ask_a.json()
    assert body["answer"]
    assert len(body["citations"]) >= 1
    assert all(c["document_id"] == uploaded["document_id"] for c in body["citations"])
    assert any(phrase.split("-")[0] in c["snippet"] for c in body["citations"])

    ask_b = client.post("/v1/ask", headers=hb, json={"question": phrase, "limit": 5})
    assert ask_b.status_code == 200, ask_b.text
    assert ask_b.json()["citations"] == []

    usage = client.get("/v1/usage", headers=ha)
    assert usage.status_code == 200
    assert any(row["operation"] in {"ask", "learn"} for row in usage.json())


def test_validate_citations_requires_tenant_acl_filter():
    sig = inspect.signature(validate_citations)
    assert "tenant_id" in sig.parameters
    assert "user_id" in sig.parameters
    src = inspect.getsource(validate_citations)
    assert "readable_document_ids" in src
    assert "Chunk.tenant_id == tenant_id" in src
