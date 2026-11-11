"""
LLM providers.

Almost every AI vendor (OpenAI, Gemini, Groq, Cerebras, Mistral, OpenRouter) and every
local server (Ollama, llama.cpp, LM Studio) offers an "OpenAI-compatible" API.
So ONE class works for all of them; only base_url / model / key differ.

To add another vendor: add one entry to _REGISTRY below and put <PREFIX>_API_KEY in .env.

provider="auto" (the default) tries the providers listed in PROVIDER_ORDER one by one:
if one is rate-limited, out of credit, or down, the next one is used automatically.
"""

import logging
import os
from abc import ABC, abstractmethod

from openai import OpenAI

from .config import get_settings

log = logging.getLogger("local-llm")


class ProviderError(Exception):
    """Provider is missing, misconfigured, or the model call failed."""


class LLMProvider(ABC):
    name: str
    model: str

    @abstractmethod
    def chat(
        self, messages: list[dict], temperature: float = 0.0, json_mode: bool = False
    ) -> str:
        """Send messages, return the assistant's text."""


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self, name: str, api_key: str, base_url: str, model: str, timeout: int
    ):
        self.name = name
        self.model = model
        # max_retries=1: don't waste time retrying a rate-limited provider; fall back instead
        self._client = OpenAI(
            api_key=api_key, base_url=base_url, timeout=timeout, max_retries=1
        )

    def chat(self, messages, temperature=0.0, json_mode=False) -> str:
        kwargs = dict(model=self.model, messages=messages, temperature=temperature)
        try:
            if json_mode:
                try:
                    resp = self._client.chat.completions.create(
                        **kwargs, response_format={"type": "json_object"}
                    )
                except Exception:
                    # Some providers/models don't support response_format; retry plainly.
                    resp = self._client.chat.completions.create(**kwargs)
            else:
                resp = self._client.chat.completions.create(**kwargs)
        except Exception as exc:  # network, auth, rate limit, model not found...
            raise ProviderError(
                f"{self.name} failed: {type(exc).__name__}: {exc}"
            ) from exc
        return resp.choices[0].message.content or ""


class FallbackProvider(LLMProvider):
    """Tries several providers in order until one answers."""

    def __init__(self, providers: list[LLMProvider]):
        self.providers = providers
        self.name = "auto"
        self.model = ""

    def chat(self, messages, temperature=0.0, json_mode=False) -> str:
        errors = []
        for provider in self.providers:
            try:
                text = provider.chat(messages, temperature, json_mode)
            except ProviderError as exc:
                log.warning(
                    "provider %s failed, trying next: %s", provider.name, str(exc)[:200]
                )
                errors.append(f"{provider.name}: {str(exc)[:150]}")
                continue
            self.name, self.model = (
                provider.name,
                provider.model,
            )  # report who really answered
            return text
        raise ProviderError("All providers failed -> " + " | ".join(errors))


# name -> (env prefix, default base_url, default model, key needed?)
# Model names change over time: if one stops working, edit <PREFIX>_MODEL in .env.
_REGISTRY = {
    "gemini": {
        "prefix": "GEMINI",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-2.5-flash",
    },
    "groq": {
        "prefix": "GROQ",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
    },
    "openrouter": {
        "prefix": "OPENROUTER",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "meta-llama/llama-3.3-70b-instruct:free",
    },
    "openai": {
        "prefix": "OPENAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    "local": {
        "prefix": "LOCAL",
        "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5-coder:3b",
        "default_key": "ollama",
    },
}


def _cfg(name: str) -> dict:
    r = _REGISTRY[name]
    p = r["prefix"]
    return {
        "api_key": os.getenv(f"{p}_API_KEY", r.get("default_key", "")).strip(),
        "base_url": os.getenv(f"{p}_BASE_URL", r["base_url"]).strip(),
        "model": os.getenv(f"{p}_MODEL", r["model"]).strip(),
    }


def available_providers() -> dict[str, dict]:
    return {
        n: {"configured": bool(_cfg(n)["api_key"]), "default_model": _cfg(n)["model"]}
        for n in _REGISTRY
    }


def _build(name: str, model: str | None = None) -> OpenAICompatibleProvider:
    cfg = _cfg(name)
    if not cfg["api_key"]:
        raise ProviderError(f"{_REGISTRY[name]['prefix']}_API_KEY is not set in .env")
    return OpenAICompatibleProvider(
        name,
        cfg["api_key"],
        cfg["base_url"],
        model or cfg["model"],
        get_settings().request_timeout,
    )


def get_provider(name: str | None = None, model: str | None = None) -> LLMProvider:
    s = get_settings()
    name = (name or s.default_provider).lower()

    if (
        name == "auto"
    ):  # fallback chain; "model" is ignored because each provider has its own
        order = [n.strip().lower() for n in s.provider_order.split(",") if n.strip()]
        chain = [_build(n) for n in order if n in _REGISTRY and _cfg(n)["api_key"]]
        if not chain:
            raise ProviderError(
                "No provider configured. Add at least one API key to .env"
            )
        return FallbackProvider(chain)

    if name not in _REGISTRY:
        raise ProviderError(
            f'Unknown provider "{name}". Use "auto" or one of: {", ".join(_REGISTRY)}'
        )
    return _build(name, model)
