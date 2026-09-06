from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Iterator

from hf_integration.chat import ChatSession
from hf_integration.client import ChatResult, HuggingFaceClient
from hf_integration.config import Settings


class ScriptedInference:
    def __init__(self) -> None:
        self.replies = ["first reply", "second reply"]
        self.calls: list[list[dict[str, str]]] = []

    def chat_completion(self, messages, **kwargs):  # noqa: ANN001
        self.calls.append(list(messages))
        if kwargs.get("stream"):
            text = self.replies.pop(0)

            def _gen() -> Iterator[Any]:
                for ch in text:
                    yield SimpleNamespace(
                        choices=[SimpleNamespace(delta=SimpleNamespace(content=ch))]
                    )

            return _gen()

        text = self.replies.pop(0)
        return SimpleNamespace(
            model="mock",
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content=text),
                )
            ],
            usage=None,
        )


def _session() -> tuple[ChatSession, ScriptedInference]:
    inference = ScriptedInference()
    client = HuggingFaceClient(
        Settings(model="mock/chat"),
        inference_client=inference,  # type: ignore[arg-type]
        hub_api=SimpleNamespace(),  # type: ignore[arg-type]
    )
    return ChatSession(client, system="be brief"), inference


def test_chat_session_keeps_history() -> None:
    session, inference = _session()
    first = session.ask("hello")
    assert isinstance(first, ChatResult)
    assert first.content == "first reply"

    second = session.ask("again")
    assert isinstance(second, ChatResult)
    assert second.content == "second reply"

    history = session.history()
    assert [m["role"] for m in history] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert history[0]["content"] == "hello"
    assert history[1]["content"] == "first reply"

    # second request includes prior turns + system
    assert inference.calls[1][0]["role"] == "system"
    assert inference.calls[1][1]["content"] == "hello"
    assert inference.calls[1][2]["content"] == "first reply"
    assert inference.calls[1][3]["content"] == "again"


def test_chat_session_stream_and_reset() -> None:
    session, _ = _session()
    chunks = list(session.ask("stream", stream=True))  # type: ignore[arg-type]
    assert "".join(chunks) == "first reply"
    assert session.history()[-1]["content"] == "first reply"

    session.reset()
    assert session.history() == []
