"""
HTTP layer. Start with:  uvicorn app.main:app --host 127.0.0.1 --port 8001

Bind to 127.0.0.1 so ONLY your Node server (same machine / private network) can reach it.
"""
import hmac
import logging
from functools import lru_cache

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from . import service
from .config import get_settings
from .models import (ChatRequest, ChatResponse, SqlFixRequest, SqlRequest, SqlResponse,
                     VisualRequest, VisualResponse)
from .providers import ProviderError, available_providers, get_provider
from .schema_store import SchemaStore

log = logging.getLogger("local-llm")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Internal AI service (SQL + visuals + chat)")


@lru_cache
def default_store() -> SchemaStore:
    s = get_settings()
    return SchemaStore.from_files(s.schema_file, s.examples_file)


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


@app.get("/providers", dependencies=[Depends(require_key)])
def providers():
    return {"default": get_settings().default_provider, "providers": available_providers()}


@app.post("/sql", response_model=SqlResponse, dependencies=[Depends(require_key)])
def sql(req: SqlRequest):
    provider = get_provider(req.provider, req.model)
    result = service.generate_sql(provider, store_for(req.schema_override), req.question, req.previous_sql)
    log.info("sql generated provider=%s ok=%s", provider.name, bool(result["sql"]))  # never log the question text
    return SqlResponse(**result, provider=provider.name, model=provider.model)


@app.post("/sql/fix", response_model=SqlResponse, dependencies=[Depends(require_key)])
def sql_fix(req: SqlFixRequest):
    provider = get_provider(req.provider, req.model)
    result = service.fix_sql(provider, store_for(req.schema_override), req.sql, req.error, req.question)
    return SqlResponse(**result, provider=provider.name, model=provider.model)


@app.post("/visual", response_model=VisualResponse, dependencies=[Depends(require_key)])
def visual(req: VisualRequest):
    provider = get_provider(req.provider, req.model)
    content = service.generate_visual(provider, req.question, req.columns, req.format)
    return VisualResponse(format=req.format, content=content, provider=provider.name, model=provider.model)


@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(require_key)])
def chat(req: ChatRequest):
    provider = get_provider(req.provider, req.model)
    messages = [m.model_dump() for m in req.messages]
    reply = service.chat(provider, default_store(), messages, req.include_schema)
    return ChatResponse(reply=reply, provider=provider.name, model=provider.model)
