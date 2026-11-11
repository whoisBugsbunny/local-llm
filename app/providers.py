"""
LLM providers.

Almost every AI vendor (OpenAI, Gemini, Groq, Cerebras, Mistral, OpenRouter) and every
local server (Ollama, llama.cpp, LM Studio) offers an "OpenAI-compatible" API.
So ONE class works for all of them; only base_url / model / key differ.

To add another vendor: add one entry to _REGISTRY below and put <PREFIX>_API_KEY in .env.

provider="auto" (the default) tries the providers listed in PROVIDER_ORDER one by one:
if one is rate-limited, out of credit, too slow, or down, the next one is used automatically.

Optional per-provider settings in .env (replace GROQ with GEMINI, OPENROUTER, ...):
GROQ_REASONING_EFFORT=low     # low | medium | high  -> reasoning models answer MUCH faster on "low"
GROQ_TIMEOUT=30               # seconds to wait before giving up and trying the next provider
"""

import logging
import os
import time
from abc import ABC, abstractmethod

from openai import OpenAI

from .config import get_settings

log = logging.getLogger("local-llm")


class ProviderError(Exception):
    """Provider is missing, misconfigured, too slow, or the model call failed."""


class LLMProvider(ABC):
    name: str
    model: str

    @abstractmethod
    def chat(
        self, messages: list[dict], temperature: float = 0.0, json_mode: bool = False
    ) -> str:
        """Send messages, return the assistant's text."""


def _describe(exc: Exception) -> str:
    """Error text plus the provider's response body (that is where the real reason is)."""
    body = ""
    resp = getattr(exc, "response", None)
    if resp is not None:
        try:
            body = resp.text[:300]
        except Exception:
            pass
    return f"{type(exc).__name__}: {body or exc}"


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        name: str,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float,
        reasoning_effort: str | None = None,
    ):
        self.name = name
        self.model = model
        self.base_url = base_url
        self.reasoning_effort = reasoning_effort
        # max_retries=0: if a provider is slow or rate-limited we move to the next one instead of waiting
        self._client = OpenAI(
            api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0
        )

    def chat(self, messages, temperature=0.0, json_mode=False) -> str:
        base = dict(model=self.model, messages=messages, temperature=temperature)
        full = dict(base)
        if self.reasoning_effort:
            full["reasoning_effort"] = self.reasoning_effort
        if json_mode:
            full["response_format"] = {"type": "json_object"}

        # Richest request first. Only if the provider says "400 bad request" (it does not
        # understand an optional feature) do we retry without that feature.
        variants = [full]
        if self.reasoning_effort:
            variants.append({k: v for k, v in full.items() if k != "reasoning_effort"})
        if json_mode:
            variants.append(base)

        last_exc = None
        for kwargs in variants:
            try:
                resp = self._client.chat.completions.create(**kwargs)
                return resp.choices[0].message.content or ""
            except Exception as exc:
                last_exc = exc
                if getattr(exc, "status_code", None) not in (400, 422):
                    break  # timeout / rate limit / auth / 5xx: retrying the same provider will not help
        raise ProviderError(
            f"{self.name} failed (model={self.model}, url={self.base_url}): {_describe(last_exc)}"
        ) from last_exc


class FallbackProvider(LLMProvider):
    """Tries several providers in order until one answers."""

    def __init__(self, providers: list[LLMProvider]):
        self.providers = providers
        self.name = "auto"
        self.model = ""

    def chat(self, messages, temperature=0.0, json_mode=False) -> str:
        errors = []
        for provider in self.providers:
            started = time.perf_counter()
            log.info("trying provider %s (%s)", provider.name, provider.model)
            try:
                text = provider.chat(messages, temperature, json_mode)
            except ProviderError as exc:
                took = time.perf_counter() - started
                log.warning(
                    "provider %s failed after %.1fs, trying next: %s",
                    provider.name,
                    took,
                    str(exc)[:200],
                )
                errors.append(f"{provider.name}: {str(exc)[:150]}")
                continue
            log.info(
                "provider %s answered in %.1fs",
                provider.name,
                time.perf_counter() - started,
            )
            self.name, self.model = (
                provider.name,
                provider.model,
            )  # report who really answered
            return text
        raise ProviderError("All providers failed -> " + " | ".join(errors))


# name -> env prefix, default base_url, default model
# Model names change over time: if one stops working, run scripts/check_providers.py
_REGISTRY = {
    "gemini": {
        "prefix": "GEMINI",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-3.1-flash-lite",
    },
    "groq": {
        "prefix": "GROQ",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "openai/gpt-oss-120b",
    },
    "cerebras": {
        "prefix": "CEREBRAS",
        "base_url": "https://api.cerebras.ai/v1",
        "model": "llama-3.3-70b",
    },
    "mistral": {
        "prefix": "MISTRAL",
        "base_url": "https://api.mistral.ai/v1",
        "model": "mistral-small-latest",
    },
    "openrouter": {
        "prefix": "OPENROUTER",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "google/gemma-4-31b-it:free",
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
        "reasoning_effort": os.getenv(f"{p}_REASONING_EFFORT", "").strip() or None,
        "timeout": float(
            os.getenv(f"{p}_TIMEOUT", "") or get_settings().request_timeout
        ),
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
        cfg["timeout"],
        cfg["reasoning_effort"],
    )


def list_models(name: str) -> list[str]:
    """Ask the provider which model names this key can use (fixes 404 'model not found')."""
    if name not in _REGISTRY:
        raise ProviderError(f"Unknown provider: {name}")
    cfg = _cfg(name)
    if not cfg["api_key"]:
        raise ProviderError(f"{_REGISTRY[name]['prefix']}_API_KEY is not set in .env")
    try:
        client = OpenAI(
            api_key=cfg["api_key"], base_url=cfg["base_url"], timeout=30, max_retries=0
        )
        return sorted(m.id.removeprefix("models/") for m in client.models.list())
    except Exception as exc:
        raise ProviderError(
            f"{name} could not list models (url={cfg['base_url']}): {_describe(exc)}"
        ) from exc


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
