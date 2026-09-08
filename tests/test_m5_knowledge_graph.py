from pathlib import Path

from fastapi.testclient import TestClient
from shared.config import get_settings
from shared.db import init_db, reset_engine
from shared.graph import normalize_name, normalize_predicate, normalize_type, rule_extract


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'kg.db'}")
    monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long!!")
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(tmp_path / "objects"))
    monkeypatch.setenv("PROFILE", "personal")
    monkeypatch.setenv("LLM_PROVIDER", "local")
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


def test_normalize_helpers():
    assert normalize_name("  OpenAI   Inc ") == "openai inc"
    assert normalize_type("Person") == "person"
    assert normalize_type("weird") == "other"
    pred, raw = normalize_predicate("works_at")
    assert pred == "works_at" and raw is None
    pred, raw = normalize_predicate("employed_by")
    assert pred == "related_to" and raw == "employed_by"


def test_rule_extract_finds_entities_and_relations():
    text = (
        "Alice works at Acme Corporation. "
        "The Nebula Protocol defines retrieval. "
        "See 《Internal Handbook》 for details."
    )
    payload = rule_extract(text)
    names = {normalize_name(e["name"]) for e in payload["entities"]}
    assert "acme corporation" in names or "nebula protocol" in names or "alice" in names
    assert "internal handbook" in names
    assert any(r.get("predicate") == "works_at" for r in payload["relations"])


def test_extract_and_list_entities(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.get("/v1/meta").json()["milestone"] in {"Knowledge-Graph", "Education-KB"}
    reg = _register(client, "kgco", "admin@kgco.example")
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    ws = client.get("/v1/workspaces", headers=headers).json()[0]

    body = (
        "# Acme Notes\n\n"
        "Alice works at Acme Corporation on the Nebula Protocol.\n\n"
        "Bob works at Acme Corporation in Research Lab.\n"
    )
    uploaded = _upload_indexed(client, headers, ws["id"], "acme.md", body)

    job = client.post(
        "/v1/graph/extract",
        headers=headers,
        json={"document_id": uploaded["document_id"], "force": False},
    )
    assert job.status_code == 200, job.text
    payload = job.json()
    assert payload["status"] == "succeeded"
    assert payload["entities_created"] >= 1

    entities = client.get("/v1/graph/entities", headers=headers)
    assert entities.status_code == 200, entities.text
    rows = entities.json()
    assert len(rows) >= 1

    stats = client.get("/v1/graph/stats", headers=headers)
    assert stats.status_code == 200
    assert stats.json()["entities"] >= 1
    assert stats.json()["documents_covered"] >= 1

    detail = client.get(f"/v1/graph/entities/{rows[0]['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["mentions"]

    nb = client.get(f"/v1/graph/entities/{rows[0]['id']}/neighbors", headers=headers)
    assert nb.status_code == 200
    assert "center" in nb.json()


def test_graph_acl_hides_entities_from_other_tenant(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    a = _register(client, "kg-a", "a@kg.example")
    b = _register(client, "kg-b", "b@kg.example")
    ha = {"Authorization": f"Bearer {a['access_token']}"}
    hb = {"Authorization": f"Bearer {b['access_token']}"}
    ws = client.get("/v1/workspaces", headers=ha).json()[0]

    uploaded = _upload_indexed(
        client,
        ha,
        ws["id"],
        "secret.md",
        "Zelda works at Hyrule Institute on the Triforce Project.\n",
    )
    job = client.post(
        "/v1/graph/extract",
        headers=ha,
        json={"document_id": uploaded["document_id"]},
    )
    assert job.status_code == 200, job.text
    assert job.json()["entities_created"] >= 1

    a_entities = client.get("/v1/graph/entities", headers=ha).json()
    assert len(a_entities) >= 1
    b_entities = client.get("/v1/graph/entities", headers=hb).json()
    assert b_entities == []

    denied = client.get(f"/v1/graph/entities/{a_entities[0]['id']}", headers=hb)
    assert denied.status_code == 404


def test_ask_graph_augment_flag(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    reg = _register(client, "kgask", "admin@kgask.example")
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    ws = client.get("/v1/workspaces", headers=headers).json()[0]

    body = (
        "Carol works at Meridian Labs.\n"
        "The Meridian Protocol is used for citation retrieval.\n"
    )
    uploaded = _upload_indexed(client, headers, ws["id"], "meridian.md", body)
    job = client.post(
        "/v1/graph/extract",
        headers=headers,
        json={"document_id": uploaded["document_id"]},
    )
    assert job.status_code == 200, job.text

    ask = client.post(
        "/v1/ask",
        headers=headers,
        json={"question": "What about Meridian?", "limit": 5, "graph_augment": True},
    )
    assert ask.status_code == 200, ask.text
    data = ask.json()
    assert "answer" in data
    assert data.get("graph_augmented") in {True, False}
    # When entities matched, augment should be true
    if any("meridian" in e["name"].lower() for e in client.get("/v1/graph/entities", headers=headers).json()):
        assert data["graph_augmented"] is True
