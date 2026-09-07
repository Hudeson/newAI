from pathlib import Path

from fastapi.testclient import TestClient
from shared.config import get_settings
from shared.db import get_session_factory, init_db, reset_engine
from shared.db.models import AgentRun, AgentToolCall, DocumentAcl, Group, GroupMember
from sqlalchemy import select


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'e7.db'}")
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


def test_meta_is_e7(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.get("/v1/meta").json()["milestone"] in {"E7", "M4"}


def test_quota_enforcement_on_ask(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    reg = _register(client, "quota-co", "admin@quota.example")
    headers = {"Authorization": f"Bearer {reg['access_token']}"}

    put = client.put(
        "/v1/admin/quotas",
        headers=headers,
        json=[{"meter": "ask", "limit": 1, "window": "day"}],
    )
    assert put.status_code == 200, put.text

    first = client.post("/v1/ask", headers=headers, json={"question": "hello world"})
    assert first.status_code == 200, first.text

    second = client.post("/v1/ask", headers=headers, json={"question": "hello again"})
    assert second.status_code == 429, second.text
    assert second.json()["error"]["code"] == "quota_exceeded"

    summary = client.get("/v1/usage/summary", headers=headers)
    assert summary.status_code == 200
    ask_meter = next(m for m in summary.json() if m["meter"] == "ask")
    assert ask_meter["used"] >= 1
    assert ask_meter["limit"] == 1


def test_agent_allowlist_and_dry_run(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    reg = _register(client, "agent-co", "admin@agent.example")
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    ws = client.get("/v1/workspaces", headers=headers).json()[0]

    denied = client.post(
        "/v1/agent/runs",
        headers=headers,
        json={
            "workspace_id": ws["id"],
            "goal": "break in",
            "tool_allowlist": ["not_a_real_tool"],
        },
    )
    assert denied.status_code == 400

    run = client.post(
        "/v1/agent/runs",
        headers=headers,
        json={
            "workspace_id": ws["id"],
            "goal": "review knowledge",
            "dry_run": True,
            "tool_allowlist": ["search_knowledge", "review_summarize"],
        },
    )
    assert run.status_code == 200, run.text
    payload = run.json()
    assert payload["dry_run"] is True
    assert payload["status"] == "completed"
    assert [c["tool_name"] for c in payload["tool_calls"]] == [
        "search_knowledge",
        "review_summarize",
    ]
    assert all(c["status"] == "dry_run" for c in payload["tool_calls"])

    session = get_session_factory()()
    try:
        rows = session.scalars(select(AgentRun).where(AgentRun.tenant_id == reg["tenant_id"])).all()
        assert len(rows) == 1
        calls = session.scalars(select(AgentToolCall)).all()
        assert len(calls) == 2
    finally:
        session.close()


def test_scim_group_acl(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    admin = _register(client, "scim-co", "admin@scim.example")
    headers = {"Authorization": f"Bearer {admin['access_token']}"}

    created = client.post(
        "/scim/v2/Users",
        headers=headers,
        json={
            "userName": "member@scim.example",
            "displayName": "Member",
            "emails": [{"value": "member@scim.example"}],
            "password": "password123",
        },
    )
    assert created.status_code == 201, created.text
    member_id = created.json()["id"]

    group = client.post(
        "/scim/v2/Groups",
        headers=headers,
        json={
            "displayName": "Readers",
            "externalId": "readers",
            "members": [{"value": member_id}],
        },
    )
    assert group.status_code == 201, group.text
    group_id = group.json()["id"]

    session = get_session_factory()()
    try:
        g = session.scalar(select(Group).where(Group.id == group_id))
        assert g is not None and g.source == "scim"
        members = session.scalars(select(GroupMember).where(GroupMember.group_id == group_id)).all()
        assert len(members) == 1
        # Grant a private doc via group ACL only.
        from shared.db.models import Document

        doc = Document(
            tenant_id=admin["tenant_id"],
            workspace_id=client.get("/v1/workspaces", headers=headers).json()[0]["id"],
            title="secret.md",
            status="indexed",
            created_by=admin["user_id"],
        )
        session.add(doc)
        session.flush()
        session.add(
            DocumentAcl(
                tenant_id=admin["tenant_id"],
                document_id=doc.id,
                principal_type="group",
                principal_id=group_id,
                permission="read",
            )
        )
        session.commit()
        doc_id = doc.id
    finally:
        session.close()

    login = client.post(
        "/v1/auth/login",
        json={
            "tenant_slug": "scim-co",
            "email": "member@scim.example",
            "password": "password123",
        },
    )
    assert login.status_code == 200, login.text
    mh = {"Authorization": f"Bearer {login.json()['access_token']}"}
    got = client.get(f"/v1/documents/{doc_id}", headers=mh)
    assert got.status_code == 200, got.text


def test_s3_connector_stub_sync(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    reg = _register(client, "conn-co", "admin@conn.example")
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    ws = client.get("/v1/workspaces", headers=headers).json()[0]

    created = client.post(
        "/v1/connectors",
        headers=headers,
        json={
            "workspace_id": ws["id"],
            "type": "s3",
            "name": "Inbox",
            "config": {"bucket": "kb-documents", "prefix": "inbox/"},
        },
    )
    assert created.status_code == 200, created.text
    connector_id = created.json()["id"]

    sync = client.post(f"/v1/connectors/{connector_id}/sync", headers=headers)
    assert sync.status_code == 200, sync.text
    body = sync.json()
    assert body["status"] == "completed"
    assert body["items_imported"] == 1
    assert body["detail"]["document_id"]

    docs = client.get("/v1/documents", headers=headers, params={"workspace_id": ws["id"]})
    assert docs.status_code == 200
    assert any("sample-from-s3" in d["title"] for d in docs.json())


def test_admin_audit_and_failed_jobs(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    reg = _register(client, "gov-co", "admin@gov.example")
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    audit = client.get("/v1/admin/audit-events", headers=headers)
    assert audit.status_code == 200
    jobs = client.get("/v1/admin/jobs", headers=headers, params={"status": "failed"})
    assert jobs.status_code == 200
    assert isinstance(jobs.json(), list)
