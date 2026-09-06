"""Thin wrappers around huggingface_hub InferenceClient and HfApi."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterator, Sequence, TypeVar

from huggingface_hub import HfApi, InferenceClient

from .config import Settings, apply_hub_endpoint, load_settings

T = TypeVar("T")


class HuggingFaceError(RuntimeError):
    """User-facing inference / Hub failure with a clear next step."""


def _run_inference(action: str, fn: Callable[[], T], *, has_token: bool) -> T:
    try:
        return fn()
    except StopIteration as exc:
        hint = (
            "No Inference Provider accepted this request. "
            "Set HF_TOKEN (https://huggingface.co/settings/tokens) and retry, "
            "or pass --provider hf-inference."
        )
        raise HuggingFaceError(f"{action} failed: {hint}") from exc
    except Exception as exc:  # noqa: BLE001 - normalize provider HTTP errors
        message = str(exc).strip() or type(exc).__name__
        if "401" in message and not has_token:
            message += " — set HF_TOKEN and retry."
        raise HuggingFaceError(f"{action} failed: {message}") from exc


@dataclass(frozen=True)
class ModelSummary:
    """Compact model card fields for CLI / programmatic use."""

    id: str
    pipeline_tag: str | None
    likes: int | None
    downloads: int | None
    tags: tuple[str, ...]
    private: bool | None = None
    gated: bool | str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "pipeline_tag": self.pipeline_tag,
            "likes": self.likes,
            "downloads": self.downloads,
            "tags": list(self.tags),
            "private": self.private,
            "gated": self.gated,
        }


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class ChatResult:
    content: str
    model: str
    finish_reason: str | None = None
    usage: dict[str, int] | None = None


@dataclass(frozen=True)
class GenerationResult:
    text: str
    model: str


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    model: str
    dimensions: int


class HuggingFaceClient:
    """Hub + Inference helpers with env-based defaults."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        inference_client: InferenceClient | None = None,
        hub_api: HfApi | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        apply_hub_endpoint(self.settings.endpoint)

        provider: Any = self.settings.provider
        if provider in (None, "", "none"):
            provider = None

        self._inference = inference_client or InferenceClient(
            model=self.settings.model,
            token=self.settings.token,
            provider=provider,
            timeout=self.settings.timeout,
        )
        self._hub = hub_api or HfApi(
            endpoint=self.settings.endpoint,
            token=self.settings.token,
        )

    @property
    def model(self) -> str:
        return self.settings.model

    def chat(
        self,
        messages: str | Sequence[dict[str, str] | ChatMessage],
        *,
        model: str | None = None,
        system: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.7,
        stream: bool = False,
    ) -> ChatResult | Iterator[str]:
        """Chat completion. Pass a string prompt or an OpenAI-style message list."""

        payload = self._normalize_messages(messages, system=system)
        target = model or self.settings.model

        if stream:
            return self._stream_chat(
                payload,
                model=target,
                max_tokens=max_tokens,
                temperature=temperature,
            )

        def _call() -> Any:
            return self._inference.chat_completion(
                messages=payload,
                model=target,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=False,
            )

        response = _run_inference(
            "chat",
            _call,
            has_token=self.settings.has_token,
        )
        choice = response.choices[0]
        message = choice.message
        content = message.content or ""
        usage = None
        if getattr(response, "usage", None) is not None:
            usage_obj = response.usage
            usage = {
                "prompt_tokens": int(getattr(usage_obj, "prompt_tokens", 0) or 0),
                "completion_tokens": int(getattr(usage_obj, "completion_tokens", 0) or 0),
                "total_tokens": int(getattr(usage_obj, "total_tokens", 0) or 0),
            }
        return ChatResult(
            content=content,
            model=getattr(response, "model", None) or target,
            finish_reason=getattr(choice, "finish_reason", None),
            usage=usage,
        )

    def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        max_new_tokens: int = 256,
        temperature: float = 0.7,
        return_full_text: bool = False,
    ) -> GenerationResult:
        """Raw text generation for completion-style models."""

        target = model or self.settings.model

        def _call() -> Any:
            return self._inference.text_generation(
                prompt,
                model=target,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                return_full_text=return_full_text,
            )

        text = _run_inference(
            "generate",
            _call,
            has_token=self.settings.has_token,
        )
        if not isinstance(text, str):
            text = str(text)
        return GenerationResult(text=text, model=target)

    def embed(
        self,
        text: str | Sequence[str],
        *,
        model: str | None = None,
        normalize: bool = True,
    ) -> EmbeddingResult:
        """Feature extraction / embeddings."""

        target = model or self.settings.embed_model

        def _call() -> Any:
            return self._inference.feature_extraction(
                text if isinstance(text, str) else list(text),
                model=target,
                normalize=normalize,
            )

        vectors = _run_inference(
            "embed",
            _call,
            has_token=self.settings.has_token,
        )
        # huggingface_hub returns a numpy array; convert without requiring numpy import
        as_list = vectors.tolist() if hasattr(vectors, "tolist") else list(vectors)
        if as_list and isinstance(as_list[0], (int, float)):
            rows = [list(map(float, as_list))]
        else:
            rows = [list(map(float, row)) for row in as_list]
        dims = len(rows[0]) if rows else 0
        return EmbeddingResult(vectors=rows, model=target, dimensions=dims)

    def model_info(self, repo_id: str | None = None) -> ModelSummary:
        info = self._hub.model_info(repo_id or self.settings.model)
        tags = tuple(getattr(info, "tags", None) or ())
        return ModelSummary(
            id=info.id,
            pipeline_tag=getattr(info, "pipeline_tag", None),
            likes=getattr(info, "likes", None),
            downloads=getattr(info, "downloads", None),
            tags=tags,
            private=getattr(info, "private", None),
            gated=getattr(info, "gated", None),
        )

    def search_models(
        self,
        query: str,
        *,
        limit: int = 10,
        pipeline_tag: str | None = None,
        sort: str = "downloads",
    ) -> list[ModelSummary]:
        models = self._hub.list_models(
            search=query,
            limit=limit,
            pipeline_tag=pipeline_tag,
            sort=sort,
        )
        results: list[ModelSummary] = []
        for info in models:
            results.append(
                ModelSummary(
                    id=info.id,
                    pipeline_tag=getattr(info, "pipeline_tag", None),
                    likes=getattr(info, "likes", None),
                    downloads=getattr(info, "downloads", None),
                    tags=tuple(getattr(info, "tags", None) or ()),
                    private=getattr(info, "private", None),
                    gated=getattr(info, "gated", None),
                )
            )
        return results

    def whoami(self) -> dict[str, Any]:
        """Return Hub identity when a token is configured."""

        if not self.settings.has_token:
            return {"authenticated": False, "name": None}
        data = self._hub.whoami()
        return {
            "authenticated": True,
            "name": data.get("name"),
            "type": data.get("type"),
            "email": data.get("email"),
        }

    def _stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> Iterator[str]:
        def _call() -> Any:
            return self._inference.chat_completion(
                messages=messages,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
            )

        stream = _run_inference(
            "chat",
            _call,
            has_token=self.settings.has_token,
        )
        try:
            for event in stream:
                choices = getattr(event, "choices", None) or []
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                content = getattr(delta, "content", None) if delta is not None else None
                if content:
                    yield content
        except Exception as exc:  # noqa: BLE001
            raise HuggingFaceError(f"chat stream failed: {exc}") from exc

    @staticmethod
    def _normalize_messages(
        messages: str | Sequence[dict[str, str] | ChatMessage],
        *,
        system: str | None,
    ) -> list[dict[str, str]]:
        payload: list[dict[str, str]] = []
        if system:
            payload.append({"role": "system", "content": system})

        if isinstance(messages, str):
            payload.append({"role": "user", "content": messages})
            return payload

        for item in messages:
            if isinstance(item, ChatMessage):
                payload.append(item.to_dict())
            else:
                role = str(item.get("role", "user"))
                content = str(item.get("content", ""))
                payload.append({"role": role, "content": content})
        return payload
