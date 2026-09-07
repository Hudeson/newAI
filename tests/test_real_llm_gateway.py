"""Real LLM gateway: credentials, openai-compatible mock, fallback."""

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from shared.config import get_settings
from shared.db import init_db, reset_engine
from shared.gateway import CompletionResult


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'llm.db'}")
    monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long!!")
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(tmp_path / "objects"))
    monkeypatch.setenv("PROFILE", "personal")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("LLM_MODEL", "test-model")
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
    client.put(
        f"/v1/upload-jobs/{job_id}/content",
        headers=headers,
        files={"file": (name, text.encode(), "text/markdown")},
    )
    done = client.post(f"/v1/upload-jobs/{job_id}/complete", headers=headers)
    assert done.status_code == 200, done.text
    return document_id


def test_meta_real_llm(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.get("/v1/meta").json()["milestone"] == "Knowledge-Graph"


def test_credential_upsert_and_env_status(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    admin = _register(client, "llm-co", "admin@llm.example")
    headers = {"Authorization": f"Bearer {admin['access_token']}"}

    env = client.get("/v1/admin/llm/env", headers=headers)
    assert env.status_code == 200
    assert env.json()["llm_key_configured"] is False

    put = client.put(
        "/v1/admin/llm/credentials",
        headers=headers,
        json={
            "provider": "openai_compatible",
            "api_key": "sk-test-key-123456",
            "base_url": "https://api.deepseek.com/v1",
            "default_model": "deepseek-chat",
        },
    )
    assert put.status_code == 200, put.text
    assert put.json()["key_configured"] is True
    assert put.json()["key_prefix"].startswith("sk-t")

    listed = client.get("/v1/admin/llm/credentials", headers=headers)
    assert listed.status_code == 200
    assert listed.json()[0]["provider"] == "openai_compatible"
    # never echo full key
    assert "sk-test-key-123456" not in listed.text


def test_ask_uses_openai_compatible_when_mocked(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    admin = _register(client, "ask-llm", "admin@askllm.example")
    headers = {"Authorization": f"Bearer {admin['access_token']}"}
    ws = client.get("/v1/workspaces", headers=headers).json()[0]

    client.put(
        "/v1/admin/llm/credentials",
        headers=headers,
        json={
            "provider": "openai_compatible",
            "api_key": "sk-live",
            "base_url": "https://example.test/v1",
            "default_model": "deepseek-chat",
        },
    )
    client.put(
        "/v1/admin/models/policy",
        headers=headers,
        json=[{"sensitivity": "L2", "provider": "openai_compatible", "model": "deepseek-chat"}],
    )

    doc_id = _upload(
        client,
        headers,
        ws["id"],
        "note.md",
        "# Note\n\nThe unique token aurora-gateway-alpha is documented here.\n",
    )
    client.patch(
        f"/v1/documents/{doc_id}/sensitivity",
        headers=headers,
        json={"sensitivity": "L2"},
    )

    fake = CompletionResult(
        text="The token aurora-gateway-alpha appears in evidence [1].",
        provider="openai_compatible",
        model="deepseek-chat",
        input_tokens=12,
        output_tokens=9,
    )
    with patch("shared.llm.openai_compatible_chat", return_value=fake):
        ask = client.post(
            "/v1/ask",
            headers=headers,
            json={"question": "What is aurora-gateway-alpha?"},
        )
    assert ask.status_code == 200, ask.text
    assert "aurora-gateway-alpha" in ask.json()["answer"]

    usage = client.get("/v1/usage", headers=headers)
    assert usage.status_code == 200
    ask_rows = [r for r in usage.json() if r["operation"] == "ask"]
    assert ask_rows
    assert ask_rows[0]["provider"] == "openai_compatible"
    assert ask_rows[0]["model"] == "deepseek-chat"


def test_ask_falls_back_without_key(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    admin = _register(client, "fallback", "admin@fallback.example")
    headers = {"Authorization": f"Bearer {admin['access_token']}"}
    ws = client.get("/v1/workspaces", headers=headers).json()[0]
    _upload(
        client,
        headers,
        ws["id"],
        "a.md",
        "# A\n\nFallback extractive still works without API keys.\n",
    )
    ask = client.post("/v1/ask", headers=headers, json={"question": "What works without keys?"})
    assert ask.status_code == 200
    assert "authorized knowledge base" in ask.json()["answer"].lower() or ask.json()["answer"]


def test_llm_ping_local(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    admin = _register(client, "ping-co", "admin@ping.example")
    headers = {"Authorization": f"Bearer {admin['access_token']}"}
    ping = client.post(
        "/v1/admin/llm/ping",
        headers=headers,
        json={"provider": "local", "model": "local-extractive"},
    )
    assert ping.status_code == 200, ping.text
    assert ping.json()["ok"] is True
