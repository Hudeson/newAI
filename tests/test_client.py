from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from hf_integration.client import ChatMessage, HuggingFaceClient
from hf_integration.config import Settings


class FakeInferenceClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def chat_completion(self, messages, **kwargs):  # noqa: ANN001
        self.calls.append(("chat_completion", {"messages": messages, **kwargs}))
        if kwargs.get("stream"):
            return iter(
                [
                    SimpleNamespace(
                        choices=[SimpleNamespace(delta=SimpleNamespace(content="你好"))]
                    ),
                    SimpleNamespace(
                        choices=[SimpleNamespace(delta=SimpleNamespace(content="世界"))]
                    ),
                ]
            )
        return SimpleNamespace(
            model=kwargs.get("model") or "test-model",
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content="hello from mock"),
                )
            ],
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=4, total_tokens=7),
        )

    def text_generation(self, prompt, **kwargs):  # noqa: ANN001
        self.calls.append(("text_generation", {"prompt": prompt, **kwargs}))
        return f"GEN:{prompt}"

    def feature_extraction(self, text, **kwargs):  # noqa: ANN001
        self.calls.append(("feature_extraction", {"text": text, **kwargs}))

        class Array(list):
            def tolist(self):  # noqa: ANN201
                return list(self)

        if isinstance(text, str):
            return Array([0.1, 0.2, 0.3])
        return Array([[0.1, 0.2], [0.3, 0.4]])


class FakeHubApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def model_info(self, repo_id, **kwargs):  # noqa: ANN001
        self.calls.append(("model_info", {"repo_id": repo_id, **kwargs}))
        return SimpleNamespace(
            id=repo_id,
            pipeline_tag="text-generation",
            likes=10,
            downloads=100,
            tags=["transformers", "pytorch"],
            private=False,
            gated=False,
        )

    def list_models(self, **kwargs):  # noqa: ANN001
        self.calls.append(("list_models", dict(kwargs)))
        return [
            SimpleNamespace(
                id="org/a",
                pipeline_tag="text-generation",
                likes=1,
                downloads=50,
                tags=["a"],
                private=False,
                gated=False,
            ),
            SimpleNamespace(
                id="org/b",
                pipeline_tag="feature-extraction",
                likes=2,
                downloads=40,
                tags=["b"],
                private=False,
                gated=False,
            ),
        ]

    def whoami(self):  # noqa: ANN201
        return {"name": "tester", "type": "user", "email": "t@example.com"}


@pytest.fixture
def client() -> HuggingFaceClient:
    settings = Settings(
        token="hf_test",
        model="mock/chat",
        embed_model="mock/embed",
        provider="auto",
        timeout=30.0,
    )
    return HuggingFaceClient(
        settings,
        inference_client=FakeInferenceClient(),  # type: ignore[arg-type]
        hub_api=FakeHubApi(),  # type: ignore[arg-type]
    )


def test_chat_string_prompt(client: HuggingFaceClient) -> None:
    result = client.chat("ping", system="sys")
    assert result.content == "hello from mock"
    assert result.model == "mock/chat"
    assert result.finish_reason == "stop"
    assert result.usage == {
        "prompt_tokens": 3,
        "completion_tokens": 4,
        "total_tokens": 7,
    }
    call = client._inference.calls[0]  # type: ignore[attr-defined]
    assert call[0] == "chat_completion"
    assert call[1]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "ping"},
    ]


def test_chat_message_objects(client: HuggingFaceClient) -> None:
    result = client.chat(
        [
            ChatMessage(role="user", content="hi"),
            {"role": "assistant", "content": "yo"},
            {"role": "user", "content": "again"},
        ]
    )
    assert result.content == "hello from mock"
    messages = client._inference.calls[0][1]["messages"]  # type: ignore[attr-defined]
    assert messages[0]["role"] == "user"
    assert messages[-1]["content"] == "again"


def test_chat_stream(client: HuggingFaceClient) -> None:
    chunks = list(client.chat("stream me", stream=True))  # type: ignore[arg-type]
    assert chunks == ["你好", "世界"]


def test_generate(client: HuggingFaceClient) -> None:
    result = client.generate("abc", max_new_tokens=8)
    assert result.text == "GEN:abc"
    assert result.model == "mock/chat"


def test_embed_single_and_batch(client: HuggingFaceClient) -> None:
    one = client.embed("hello")
    assert one.dimensions == 3
    assert one.vectors == [[0.1, 0.2, 0.3]]
    assert one.model == "mock/embed"

    many = client.embed(["a", "b"])
    assert many.dimensions == 2
    assert many.vectors == [[0.1, 0.2], [0.3, 0.4]]


def test_model_info_and_search(client: HuggingFaceClient) -> None:
    info = client.model_info()
    assert info.id == "mock/chat"
    assert info.pipeline_tag == "text-generation"
    assert "transformers" in info.tags

    found = client.search_models("llama", limit=2, pipeline_tag="text-generation")
    assert [m.id for m in found] == ["org/a", "org/b"]
    assert found[0].to_dict()["downloads"] == 50


def test_whoami(client: HuggingFaceClient) -> None:
    data = client.whoami()
    assert data["authenticated"] is True
    assert data["name"] == "tester"


def test_whoami_without_token() -> None:
    settings = Settings(token=None, model="x")
    client = HuggingFaceClient(
        settings,
        inference_client=FakeInferenceClient(),  # type: ignore[arg-type]
        hub_api=FakeHubApi(),  # type: ignore[arg-type]
    )
    assert client.whoami() == {"authenticated": False, "name": None}


def test_generate_wraps_stop_iteration() -> None:
    class Boom:
        def text_generation(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise StopIteration

    client = HuggingFaceClient(
        Settings(token=None, model="x"),
        inference_client=Boom(),  # type: ignore[arg-type]
        hub_api=FakeHubApi(),  # type: ignore[arg-type]
    )
    with pytest.raises(Exception) as caught:
        client.generate("hi")
    assert "HF_TOKEN" in str(caught.value)
