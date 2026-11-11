"""
The "brain": talks to the model, checks the answer, retries with feedback if it is wrong.
Read generate_sql() first; everything else follows the same pattern.
"""
import json
import re

from . import code_guard, prompts
from .config import get_settings
from .providers import LLMProvider
from .schema_store import SchemaStore
from .sql_guard import SqlRejected, validate_sql


class ModelOutputError(Exception):
    """The model kept returning something unusable."""


def _parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)  # model added chatter around the JSON
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    raise ModelOutputError("Model did not return valid JSON")


# ------------------------------------------------------------------ SQL
def generate_sql(provider: LLMProvider, store: SchemaStore, question: str, previous_sql: str | None = None) -> dict:
    s = get_settings()
    tables = store.select_tables(question, s.max_tables_in_prompt)
    messages = [
        {"role": "system", "content": prompts.SQL_SYSTEM},
        {"role": "user", "content": prompts.build_sql_user_message(store, tables, question, previous_sql)},
    ]
    return _sql_loop(provider, store, messages)


def fix_sql(provider: LLMProvider, store: SchemaStore, sql: str, error: str, question: str | None = None) -> dict:
    s = get_settings()
    tables = store.select_tables((question or "") + " " + sql, s.max_tables_in_prompt)
    messages = [
        {"role": "system", "content": prompts.SQL_SYSTEM},
        {"role": "user", "content": prompts.build_fix_message(store, tables, sql, error, question)},
    ]
    return _sql_loop(provider, store, messages)


def _sql_loop(provider: LLMProvider, store: SchemaStore, messages: list[dict]) -> dict:
    s = get_settings()
    allowed = store.table_names() if s.enforce_table_whitelist else None
    last_problem = "unknown"

    for _ in range(s.max_repair_attempts + 1):
        raw = provider.chat(messages, json_mode=True)

        try:
            data = _parse_json(raw)
        except ModelOutputError as exc:
            last_problem = str(exc)
            messages += [{"role": "assistant", "content": raw},
                         {"role": "user", "content": "Reply with valid JSON only, in the requested shape."}]
            continue

        if not data.get("sql"):  # model asks a question instead of guessing
            return {"sql": None,
                    "explanation": data.get("explanation") or "",
                    "clarifying_question": data.get("clarifying_question"),
                    "tables_used": []}

        try:
            clean_sql = validate_sql(data["sql"], allowed, s.max_rows)
        except SqlRejected as exc:
            last_problem = str(exc)
            messages += [{"role": "assistant", "content": raw},
                         {"role": "user", "content": f"That SQL was rejected: {exc}. Return corrected JSON."}]
            continue

        used = [t.name for t in store.payload.tables if re.search(rf"\b{re.escape(t.name)}\b", clean_sql, re.I)]
        return {"sql": clean_sql,
                "explanation": data.get("explanation") or "",
                "clarifying_question": None,
                "tables_used": used}

    raise ModelOutputError(f"Model could not produce valid SQL: {last_problem}")


# ------------------------------------------------------------------ visuals
_CHART_TYPES = {"bar", "line", "area", "pie", "table", "kpi"}


def generate_visual(provider: LLMProvider, question: str, columns: list, fmt: str):
    messages = [
        {"role": "system", "content": prompts.VISUAL_SYSTEM[fmt]},
        {"role": "user", "content": prompts.build_visual_message(question, columns)},
    ]
    names = {c.name for c in columns}

    if fmt == "spec":
        spec = _parse_json(provider.chat(messages, json_mode=True))
        if spec.get("chart_type") not in _CHART_TYPES:
            raise ModelOutputError("Model returned an unknown chart_type")
        used = ([spec["x"]] if spec.get("x") else []) + list(spec.get("y") or [])
        bad = [c for c in used if c not in names]
        if bad:
            raise ModelOutputError(f"Model used unknown column(s): {', '.join(bad)}")
        return spec

    code = code_guard.strip_fences(provider.chat(messages))
    try:
        code_guard.validate_code(code)
    except code_guard.CodeRejected as exc:
        raise ModelOutputError(str(exc)) from exc
    return code


# ------------------------------------------------------------------ chat
def chat(provider: LLMProvider, store: SchemaStore, messages: list[dict], include_schema: bool) -> str:
    system = prompts.CHAT_SYSTEM
    if include_schema:
        brief = "; ".join(f"{t.name}({', '.join(c.name for c in t.columns[:15])})" for t in store.payload.tables[:30])
        system += "\n\nTables available in the reporting database (names only): " + brief
    return provider.chat([{"role": "system", "content": system}, *messages], temperature=0.3)
