from __future__ import annotations

import os

import pytest

from hf_integration.config import (
    DEFAULT_CHAT_MODEL,
    DEFAULT_EMBED_MODEL,
    apply_hub_endpoint,
    load_settings,
)


def test_load_settings_defaults(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Avoid picking up the project's local .env while asserting pure defaults.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_HUB_TOKEN", raising=False)
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    monkeypatch.delenv("HF_MODEL", raising=False)
    monkeypatch.delenv("HF_EMBED_MODEL", raising=False)
    monkeypatch.delenv("HF_PROVIDER", raising=False)
    monkeypatch.delenv("HF_TIMEOUT", raising=False)

    settings = load_settings()
    assert settings.token is None
    assert settings.endpoint is None
    assert settings.model == DEFAULT_CHAT_MODEL
    assert settings.embed_model == DEFAULT_EMBED_MODEL
    assert settings.provider == "auto"
    assert settings.timeout == 60.0
    assert settings.has_token is False


def test_load_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf_test_token")
    monkeypatch.setenv("HF_ENDPOINT", "https://hf-mirror.com/")
    monkeypatch.setenv("HF_MODEL", "org/chat-model")
    monkeypatch.setenv("HF_EMBED_MODEL", "org/embed-model")
    monkeypatch.setenv("HF_PROVIDER", "hf-inference")
    monkeypatch.setenv("HF_TIMEOUT", "12.5")

    settings = load_settings()
    assert settings.token == "hf_test_token"
    assert settings.endpoint == "https://hf-mirror.com/"
    assert settings.model == "org/chat-model"
    assert settings.embed_model == "org/embed-model"
    assert settings.provider == "hf-inference"
    assert settings.timeout == 12.5
    assert settings.has_token is True


def test_explicit_overrides_beat_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "env_token")
    monkeypatch.setenv("HF_MODEL", "env/model")

    settings = load_settings(token="arg_token", model="arg/model")
    assert settings.token == "arg_token"
    assert settings.model == "arg/model"


def test_apply_hub_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    apply_hub_endpoint(None)
    assert "HF_ENDPOINT" not in os.environ

    apply_hub_endpoint("https://hf-mirror.com/")
    assert os.environ["HF_ENDPOINT"] == "https://hf-mirror.com"


def test_load_dotenv_fills_missing_env(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("HF_TOKEN=hf_from_file\nHF_MODEL=org/from-file\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HF_MODEL", raising=False)

    from hf_integration.config import load_settings

    settings = load_settings()
    assert settings.token == "hf_from_file"
    assert settings.model == "org/from-file"


def test_load_dotenv_does_not_override_existing(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("HF_TOKEN=hf_from_file\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HF_TOKEN", "hf_from_env")

    from hf_integration.config import load_settings

    settings = load_settings()
    assert settings.token == "hf_from_env"
