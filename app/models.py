"""Request / response shapes (validated automatically by FastAPI)."""
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------- schema ----------
class Column(BaseModel):
    name: str
    type: str = "unknown"
    description: str = ""


class Table(BaseModel):
    name: str
    description: str = ""
    columns: list[Column]


class SchemaPayload(BaseModel):
    schema_name: str = "VTF"
    glossary: dict[str, str] = {}
    tables: list[Table]


# ---------- shared ----------
class ProviderChoice(BaseModel):
    provider: Optional[str] = Field(None, description='"openai" or "local"')
    model: Optional[str] = Field(None, description="Override the default model name")


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


# ---------- /sql ----------
class SqlRequest(ProviderChoice):
    question: str = Field(min_length=3, max_length=2000)
    previous_sql: Optional[str] = Field(None, max_length=20000, description="For follow-ups like 'now group by city'")
    schema_override: Optional[SchemaPayload] = Field(None, description="Send a live schema instead of schema.json")


class SqlFixRequest(ProviderChoice):
    sql: str = Field(max_length=20000)
    error: str = Field(max_length=4000, description="Database error message")
    question: Optional[str] = Field(None, max_length=2000)
    schema_override: Optional[SchemaPayload] = None


class SqlResponse(BaseModel):
    sql: Optional[str]
    explanation: str = ""
    clarifying_question: Optional[str] = None
    tables_used: list[str] = []
    provider: str
    model: str
    execution_time_ms: float


# ---------- /visual ----------
class ColumnInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    type: str = "unknown"


class VisualRequest(ProviderChoice):
    # extra="forbid": if someone accidentally sends "rows", the request is REJECTED.
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=2000)
    columns: list[ColumnInfo] = Field(min_length=1)
    format: Literal["spec", "tsx", "html", "js"] = "spec"


class VisualResponse(BaseModel):
    format: str
    content: Any  # dict for "spec", string for code
    provider: str
    model: str
    execution_time_ms: float


# ---------- /chat ----------
class ChatRequest(ProviderChoice):
    messages: list[ChatMessage] = Field(min_length=1, max_length=30)
    include_schema: bool = True


class ChatResponse(BaseModel):
    reply: str
    provider: str
    model: str
    execution_time_ms: float
