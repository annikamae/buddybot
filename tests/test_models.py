from types import SimpleNamespace

import pytest

import buddy_models
from buddy_models import create_chat_model, discover_ollama_models


def test_discovery_excludes_cloud_routed_models(monkeypatch):
    class FakeClient:
        def __init__(self, **kwargs):
            del kwargs

        def list(self):
            return SimpleNamespace(
                models=[
                    SimpleNamespace(model="llama3.2:latest"),
                    SimpleNamespace(model="remote-cloud"),
                    SimpleNamespace(model="vision:cloud"),
                    SimpleNamespace(model=None),
                ]
            )

    monkeypatch.setattr(buddy_models, "Client", FakeClient)
    assert discover_ollama_models() == ["llama3.2:latest"]


def test_cloud_model_requires_explicit_consent(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-placeholder")
    with pytest.raises(PermissionError):
        create_chat_model("openai", "gpt-4.1-mini")


def test_cloud_model_requires_process_environment_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(EnvironmentError):
        create_chat_model("openai", "gpt-4.1-mini", allow_cloud=True)


def test_cloud_model_name_is_allowlisted(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-placeholder")
    with pytest.raises(ValueError):
        create_chat_model("openai", "unlisted-model", allow_cloud=True)


def test_cloud_model_is_constructed_after_explicit_consent(monkeypatch):
    from langchain_openai import ChatOpenAI

    monkeypatch.setenv("OPENAI_API_KEY", "test-only-placeholder")
    model = create_chat_model(
        "openai",
        "gpt-4.1-mini",
        allow_cloud=True,
    )
    assert isinstance(model, ChatOpenAI)


def test_local_model_requires_nonempty_name():
    with pytest.raises(ValueError):
        create_chat_model("ollama", "  ")
