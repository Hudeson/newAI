from __future__ import annotations

from types import SimpleNamespace

from hf_integration.client import HuggingFaceClient
from hf_integration.config import Settings


def test_local_generate(monkeypatch) -> None:
    import hf_integration.local as local

    monkeypatch.setattr(local, "local_generate", lambda *a, **k: " world")
    client = HuggingFaceClient(
        Settings(provider="local", model="sshleifer/tiny-gpt2"),
        inference_client=SimpleNamespace(),  # type: ignore[arg-type]
        hub_api=SimpleNamespace(),  # type: ignore[arg-type]
    )
    result = client.generate("Hello")
    assert result.text == " world"
    assert result.model == "sshleifer/tiny-gpt2"


def test_local_chat(monkeypatch) -> None:
    import hf_integration.local as local

    monkeypatch.setattr(local, "local_chat", lambda *a, **k: "你好")
    client = HuggingFaceClient(
        Settings(provider="local", model="sshleifer/tiny-gpt2"),
        inference_client=SimpleNamespace(),  # type: ignore[arg-type]
        hub_api=SimpleNamespace(),  # type: ignore[arg-type]
    )
    result = client.chat("hi")
    assert result.content == "你好"


def test_local_embed(monkeypatch) -> None:
    import hf_integration.local as local

    monkeypatch.setattr(local, "local_embed", lambda *a, **k: [[0.1, 0.2]])
    client = HuggingFaceClient(
        Settings(provider="local", model="x", embed_model="sshleifer/tiny-gpt2"),
        inference_client=SimpleNamespace(),  # type: ignore[arg-type]
        hub_api=SimpleNamespace(),  # type: ignore[arg-type]
    )
    result = client.embed("hi")
    assert result.dimensions == 2
    assert result.vectors == [[0.1, 0.2]]
