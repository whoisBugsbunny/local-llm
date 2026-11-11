"""
LLM providers.

Both OpenAI and local servers (Ollama, llama.cpp, vLLM, LM Studio) speak the same
"OpenAI-compatible" HTTP API. So ONE class covers both; only base_url/model/key differ.
To add a different vendor later (Anthropic, Gemini...), write a new class that
implements `chat()` and register it in `get_provider()`.
"""
from abc import ABC, abstractmethod

from openai import OpenAI

from .config import Settings, get_settings


class ProviderError(Exception):
    """Provider is missing, misconfigured, or the model call failed."""


class LLMProvider(ABC):
    name: str
    model: str

    @abstractmethod
    def chat(self, messages: list[dict], temperature: float = 0.0, json_mode: bool = False) -> str:
        """Send messages, return the assistant's text."""


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, name: str, api_key: str, base_url: str, model: str, timeout: int):
        self.name = name
        self.model = model
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)

    def chat(self, messages, temperature=0.0, json_mode=False) -> str:
        kwargs = dict(model=self.model, messages=messages, temperature=temperature)
        try:
            if json_mode:
                try:
                    resp = self._client.chat.completions.create(
                        **kwargs, response_format={"type": "json_object"}
                    )
                except Exception:
                    # Some local servers don't support response_format; retry plainly.
                    resp = self._client.chat.completions.create(**kwargs)
            else:
                resp = self._client.chat.completions.create(**kwargs)
        except Exception as exc:  # network, auth, model not found...
            raise ProviderError(f"{self.name} provider failed: {type(exc).__name__}: {exc}") from exc
        return resp.choices[0].message.content or ""


def available_providers(s: Settings | None = None) -> dict[str, dict]:
    s = s or get_settings()
    return {
        "openai": {"configured": bool(s.openai_api_key), "default_model": s.openai_model},
        "local": {"configured": True, "default_model": s.local_model},
    }


def get_provider(name: str | None = None, model: str | None = None) -> LLMProvider:
    s = get_settings()
    name = (name or s.default_provider).lower()

    if name == "openai":
        if not s.openai_api_key:
            raise ProviderError("OPENAI_API_KEY is not set")
        return OpenAICompatibleProvider(
            "openai", s.openai_api_key, s.openai_base_url, model or s.openai_model, s.request_timeout
        )
    if name == "local":
        return OpenAICompatibleProvider(
            "local", s.local_api_key, s.local_base_url, model or s.local_model, s.request_timeout
        )
    raise ProviderError(f'Unknown provider "{name}". Use "openai" or "local".')
