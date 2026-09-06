"""Stateful multi-turn chat helper on top of HuggingFaceClient."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Sequence

from .client import ChatMessage, ChatResult, HuggingFaceClient


class ChatSession:
    """Keep conversation history and call chat completions."""

    def __init__(
        self,
        client: HuggingFaceClient | None = None,
        *,
        system: str | None = "You are a helpful assistant.",
        model: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> None:
        self.client = client or HuggingFaceClient()
        self.system = system
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.messages: list[ChatMessage] = []

    def reset(self) -> None:
        self.messages.clear()

    def history(self) -> list[dict[str, str]]:
        return [message.to_dict() for message in self.messages]

    def ask(self, prompt: str, *, stream: bool = False) -> ChatResult | Iterator[str]:
        self.messages.append(ChatMessage(role="user", content=prompt))
        payload: Sequence[ChatMessage] = list(self.messages)

        if stream:
            chunks: list[str] = []

            def _iter() -> Iterator[str]:
                for chunk in self.client.chat(  # type: ignore[union-attr]
                    payload,
                    model=self.model,
                    system=self.system,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    stream=True,
                ):
                    chunks.append(chunk)
                    yield chunk
                self.messages.append(ChatMessage(role="assistant", content="".join(chunks)))

            return _iter()

        result = self.client.chat(
            payload,
            model=self.model,
            system=self.system,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            stream=False,
        )
        assert isinstance(result, ChatResult)
        self.messages.append(ChatMessage(role="assistant", content=result.content))
        return result
