"""Model discovery and provider construction for Buddy."""

import os

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama
from ollama import Client

OLLAMA_URL = "http://localhost:11434"
OPENAI_MODEL_NAMES = (
    "gpt-4.1-mini",
    "gpt-4.1",
    "gpt-4o-mini",
)


def discover_ollama_models(
    host: str = OLLAMA_URL,
    timeout: float = 3,
) -> list[str]:
    """Return installed local Ollama models, excluding explicitly cloud-routed tags."""
    response = Client(host=host, timeout=timeout).list()
    names = {
        model.model
        for model in response.models
        if isinstance(model.model, str)
        and model.model
        and not model.model.casefold().endswith(("-cloud", ":cloud"))
    }
    return sorted(names, key=str.casefold)


def create_chat_model(
    provider: str,
    model_name: str,
    *,
    allow_cloud: bool = False,
) -> BaseChatModel:
    if provider == "ollama":
        if not model_name.strip():
            raise ValueError("Select an installed local Ollama model.")
        return ChatOllama(
            model=model_name,
            base_url=OLLAMA_URL,
            temperature=0.2,
        )

    if provider == "openai":
        if not allow_cloud:
            raise PermissionError("Enable cloud use before selecting an OpenAI model.")
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "OpenAI cloud use requires OPENAI_API_KEY in the process environment."
            )
        if model_name not in OPENAI_MODEL_NAMES:
            raise ValueError("Select a supported OpenAI model from Buddy's model list.")
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model_name,
            api_key=api_key,
            temperature=0.2,
        )

    raise ValueError("Unsupported model provider.")
