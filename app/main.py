"""
HTTP layer. Start with:  uvicorn app.main:app --host 127.0.0.1 --port 8001

Bind to 127.0.0.1 so ONLY your Node server (same machine / private network) can reach it.
"""

import hashlib
import hmac
import json
import logging
import os
import threading
import time
from functools import lru_cache

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from . import service
from .config import get_settings
from .models import (
    ChatRequest,
    ChatResponse,
    SqlFixRequest,
    SqlRequest,
    SqlResponse,
    VisualRequest,
    VisualResponse,
)
from .providers import ProviderError, available_providers, get_provider, list_models
from .schema_store import SchemaStore

log = logging.getLogger("local-llm")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Internal AI service (SQL + visuals + chat)")


@lru_cache
def default_store() -> SchemaStore:
    s = get_settings()
    return SchemaStore.from_files(s.schema_file, s.examples_file)


# ---------- tiny in-memory answer cache (same question + same schema = instant answer) ----------
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 500


def cache_key(req: SqlRequest) -> str:
    s = get_settings()
    schema_part = (
        req.schema_override.model_dump()
        if req.schema_override
        else os.path.getmtime(s.schema_file)
    )
    raw = json.dumps(
        [
            req.question.strip().lower(),
            req.previous_sql,
            req.provider,
            req.model,
            schema_part,
        ],
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def cache_get(key: str):
    ttl = get_settings().cache_ttl_seconds
    if ttl <= 0:
        return None
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        _CACHE.pop(key, None)
    return None


def cache_put(key: str, value: dict) -> None:
    if get_settings().cache_ttl_seconds <= 0:
        return
    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.pop(min(_CACHE, key=lambda k: _CACHE[k][0]))  # drop the oldest
        _CACHE[key] = (time.time(), value)


def require_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = get_settings().service_api_key
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


def store_for(schema_override) -> SchemaStore:
    store = default_store()
    return store.with_schema(schema_override) if schema_override else store


@app.exception_handler(ProviderError)
async def provider_error_handler(_, exc: ProviderError):
    log.warning("provider error: %s", exc)
    return JSONResponse(status_code=502, content={"error": str(exc)})


@app.exception_handler(service.ModelOutputError)
async def model_output_handler(_, exc: service.ModelOutputError):
    log.warning("model output error: %s", exc)
    return JSONResponse(status_code=422, content={"error": str(exc)})


# NOTE: routes are plain `def` (not async) because the OpenAI SDK call is blocking;
# FastAPI runs them in a thread pool so one slow request doesn't block the others.


@app.get("/health")
def health():
    return {"ok": True}


def elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 2)


@app.get("/providers", dependencies=[Depends(require_key)])
def providers():
    return {
        "default": get_settings().default_provider,
        "providers": available_providers(),
    }


@app.get("/providers/{name}/models", dependencies=[Depends(require_key)])
def provider_models(name: str):
    """Which model names does this provider/key accept? Copy one into <NAME>_MODEL in .env."""
    return {"provider": name, "models": list_models(name)}


@app.post("/sql", response_model=SqlResponse, dependencies=[Depends(require_key)])
def sql(req: SqlRequest):
    started_at = time.perf_counter()
    key = cache_key(req)
    hit = cache_get(key)
    if hit:
        return SqlResponse(**hit, cached=True)
    provider = get_provider(req.provider, req.model)
    result = service.generate_sql(
        provider, store_for(req.schema_override), req.question, req.previous_sql
    )
    log.info(
        "sql generated provider=%s ok=%s", provider.name, bool(result["sql"])
    )  # never log the question text
    response = {
        **result,
        "provider": provider.name,
        "model": provider.model,
        "execution_time_ms": elapsed_ms(started_at),
    }
    if result["sql"]:
        cache_put(key, response)
    return SqlResponse(**response)


@app.post("/admin/reload", dependencies=[Depends(require_key)])
def reload_schema():
    """Re-read schema.json / examples.json without restarting (after running tools/build_schema.py)."""
    default_store.cache_clear()
    with _CACHE_LOCK:
        _CACHE.clear()
    return {
        "ok": True,
        "tables": len(default_store().payload.tables),
        "examples": len(default_store().examples),
    }


@app.post("/sql/fix", response_model=SqlResponse, dependencies=[Depends(require_key)])
def sql_fix(req: SqlFixRequest):
    started_at = time.perf_counter()
    provider = get_provider(req.provider, req.model)
    result = service.fix_sql(
        provider, store_for(req.schema_override), req.sql, req.error, req.question
    )
    return SqlResponse(
        **result,
        provider=provider.name,
        model=provider.model,
        execution_time_ms=elapsed_ms(started_at)
    )


@app.post("/visual", response_model=VisualResponse, dependencies=[Depends(require_key)])
def visual(req: VisualRequest):
    started_at = time.perf_counter()
    provider = get_provider(req.provider, req.model)
    content = service.generate_visual(provider, req.question, req.columns, req.format)
    return VisualResponse(
        format=req.format,
        content=content,
        provider=provider.name,
        model=provider.model,
        execution_time_ms=elapsed_ms(started_at),
    )


@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(require_key)])
def chat(req: ChatRequest):
    started_at = time.perf_counter()
    provider = get_provider(req.provider, req.model)
    messages = [m.model_dump() for m in req.messages]
    reply = service.chat(provider, default_store(), messages, req.include_schema)
    return ChatResponse(
        reply=reply,
        provider=provider.name,
        model=provider.model,
        execution_time_ms=elapsed_ms(started_at),
    )
