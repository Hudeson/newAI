from pathlib import Path

from fastapi.testclient import TestClient
from shared.config import get_settings
from shared.db import init_db, reset_engine
from shared.education import grade_answer
from shared.db.models import EduQuestion


def _client(tmp_path: Path, monkeypatch, *, edu_enabled: bool = True) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'edu.db'}")
    monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long!!")
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(tmp_path / "objects"))
    monkeypatch.setenv("PROFILE", "personal")
    monkeypatch.setenv("LLM_PROVIDER", "local")
    monkeypatch.setenv("EDU_ENABLED", "true" if edu_enabled else "false")
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


def test_grade_answer_helpers():
    q = EduQuestion(
        tenant_id="t",
        stem_md="x",
        qtype="fill",
        subject="math",
        stage="junior",
        answer_md="4",
    )
    assert grade_answer(q, "4") == 1
    assert grade_answer(q, " 4 ") == 1
    assert grade_answer(q, "5") == 0
    q.qtype = "essay"
    assert grade_answer(q, "anything") is None


def test_meta_milestone_education(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.get("/v1/meta").json()["milestone"] == "Education-KB"


def test_pack_requires_license(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    reg = _register(client, "edu1", "admin@edu1.example")
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    bad = client.post(
        "/v1/edu/packs",
        headers=headers,
        json={
            "name": "非法包",
            "stage": "junior",
            "subject": "math",
            "license_type": "",
        },
    )
    assert bad.status_code == 400


def test_seed_explain_similar_practice_and_tenant_isolation(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    a = _register(client, "edua", "admin@edua.example")
    b = _register(client, "edub", "admin@edub.example")
    ha = {"Authorization": f"Bearer {a['access_token']}"}
    hb = {"Authorization": f"Bearer {b['access_token']}"}

    seed = client.post("/v1/edu/packs/seed-demo", headers=ha)
    assert seed.status_code == 200, seed.text
    payload = seed.json()
    assert payload["questions"] >= 5
    assert payload["points"] >= 2

    packs = client.get("/v1/edu/packs", headers=ha)
    assert packs.status_code == 200
    assert len(packs.json()) >= 1
    assert packs.json()[0]["license_type"] == "demo"

    points = client.get("/v1/edu/points", headers=ha, params={"subject": "math"})
    assert points.status_code == 200
    assert len(points.json()) >= 2
    kp = points.json()[0]["id"]

    questions = client.get(
        "/v1/edu/questions",
        headers=ha,
        params={"subject": "math", "knowledge_point_id": kp},
    )
    assert questions.status_code == 200
    assert len(questions.json()) >= 1
    qid = questions.json()[0]["id"]

    detail = client.get(f"/v1/edu/questions/{qid}", headers=ha)
    assert detail.status_code == 200
    assert detail.json()["stem_md"]

    # Cross-tenant isolation
    other = client.get(f"/v1/edu/questions/{qid}", headers=hb)
    assert other.status_code == 404
    foreign_list = client.get("/v1/edu/questions", headers=hb)
    assert foreign_list.status_code == 200
    assert foreign_list.json() == []

    explain = client.post(
        "/v1/edu/explain",
        headers=ha,
        json={"question_id": qid, "limit": 3},
    )
    assert explain.status_code == 200, explain.text
    assert explain.json()["answer"]
    assert qid == explain.json()["question_id"] or explain.json()["question_id"] == qid

    similar = client.get("/v1/edu/similar", headers=ha, params={"question_id": qid})
    assert similar.status_code == 200
    assert isinstance(similar.json(), list)

    practice = client.post(
        "/v1/edu/practice",
        headers=ha,
        json={"mode": "drill", "filters": {"subject": "math"}, "limit": 2},
    )
    assert practice.status_code == 200, practice.text
    session_id = practice.json()["session_id"]
    pqid = practice.json()["questions"][0]["id"]
    ans = client.post(
        f"/v1/edu/practice/{session_id}/answer",
        headers=ha,
        json={"question_id": pqid, "user_answer_md": practice.json()["questions"][0]["answer_md"]},
    )
    assert ans.status_code == 200, ans.text
    assert ans.json()["is_correct"] in (0, 1, None)


def test_edu_disabled(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch, edu_enabled=False)
    reg = _register(client, "edux", "admin@edux.example")
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    resp = client.get("/v1/edu/packs", headers=headers)
    assert resp.status_code == 403
