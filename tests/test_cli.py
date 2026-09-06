from __future__ import annotations

import json
from types import SimpleNamespace

from hf_integration.cli import main
from hf_integration.client import ChatResult, EmbeddingResult, GenerationResult, ModelSummary


class StubClient:
    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        pass

    def chat(self, messages, **kwargs):  # noqa: ANN001, ANN003
        if kwargs.get("stream"):
            return iter(["hel", "lo"])
        return ChatResult(content="stub-chat", model="stub", finish_reason="stop")

    def generate(self, prompt, **kwargs):  # noqa: ANN001, ANN003
        return GenerationResult(text=f"gen:{prompt}", model="stub")

    def embed(self, text, **kwargs):  # noqa: ANN001, ANN003
        return EmbeddingResult(vectors=[[0.5, 0.25]], model="embed", dimensions=2)

    def model_info(self, repo_id=None):  # noqa: ANN001
        return ModelSummary(
            id=repo_id or "stub/model",
            pipeline_tag="text-generation",
            likes=1,
            downloads=2,
            tags=("t",),
            private=False,
            gated=False,
        )

    def search_models(self, query, **kwargs):  # noqa: ANN001, ANN003
        return [
            ModelSummary(
                id=f"hit/{query}",
                pipeline_tag="text-generation",
                likes=3,
                downloads=4,
                tags=(),
            )
        ]

    def whoami(self):  # noqa: ANN201
        return {"authenticated": True, "name": "stub-user"}


def test_cli_chat_oneshot(monkeypatch, capsys) -> None:  # noqa: ANN001
    monkeypatch.setattr("hf_integration.cli.HuggingFaceClient", StubClient)
    monkeypatch.setattr(
        "hf_integration.chat.HuggingFaceClient",
        StubClient,
    )
    # ChatSession constructs via cli._client_from_args -> HuggingFaceClient
    code = main(["chat", "hi there"])
    assert code == 0
    out = capsys.readouterr().out
    assert "stub-chat" in out


def test_cli_generate_embed_info_search_whoami(monkeypatch, capsys) -> None:  # noqa: ANN001
    monkeypatch.setattr("hf_integration.cli.HuggingFaceClient", StubClient)

    assert main(["generate", "abc"]) == 0
    assert "gen:abc" in capsys.readouterr().out

    assert main(["embed", "hello"]) == 0
    embed_out = json.loads(capsys.readouterr().out)
    assert embed_out["dimensions"] == 2
    assert embed_out["vectors"] == [[0.5, 0.25]]

    assert main(["model-info", "org/x"]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["id"] == "org/x"

    assert main(["search", "llama", "--limit", "1"]) == 0
    search = json.loads(capsys.readouterr().out)
    assert search[0]["id"] == "hit/llama"

    assert main(["whoami"]) == 0
    who = json.loads(capsys.readouterr().out)
    assert who["name"] == "stub-user"


def test_cli_chat_uses_session(monkeypatch, capsys) -> None:  # noqa: ANN001
    class SessionStub:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            self.args = args
            self.kwargs = kwargs

        def ask(self, prompt, *, stream=False):  # noqa: ANN001
            assert prompt == "ping"
            assert stream is False
            return ChatResult(content="session-ok", model="s")

    monkeypatch.setattr("hf_integration.cli.ChatSession", SessionStub)
    monkeypatch.setattr("hf_integration.cli.HuggingFaceClient", StubClient)
    assert main(["chat", "ping"]) == 0
    assert "session-ok" in capsys.readouterr().out
