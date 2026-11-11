import json

import pytest

from app import service
from app.models import ColumnInfo, SchemaPayload
from app.providers import LLMProvider
from app.schema_store import SchemaStore
from app.sql_guard import SqlRejected, validate_sql

TABLES = {"SALES_ORDERS", "CUSTOMERS"}


class FakeProvider(LLMProvider):
    """Returns pre-written answers, so tests need no API key."""

    name, model = "fake", "fake-1"

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = 0

    def chat(self, messages, temperature=0.0, json_mode=False):
        self.calls += 1
        return self.answers.pop(0)


@pytest.fixture
def store():
    return SchemaStore.from_files("schema/schema.json", "schema/examples.json")


# ---------- sql_guard ----------
def test_accepts_select_and_adds_limit():
    out = validate_sql("SELECT ORDER_ID FROM SALES_ORDERS", TABLES, 50)
    assert out.endswith("LIMIT 50")


def test_keeps_existing_limit():
    assert validate_sql("SELECT * FROM CUSTOMERS LIMIT 5", TABLES).count("LIMIT") == 1


@pytest.mark.parametrize(
    "bad",
    [
        "DELETE FROM CUSTOMERS",
        "SELECT 1 FROM CUSTOMERS; DROP TABLE CUSTOMERS",
        "UPDATE CUSTOMERS SET CITY='x'",
        "SELECT * FROM SECRET_TABLE",
        "",
    ],
)
def test_rejects_bad_sql(bad):
    with pytest.raises(SqlRejected):
        validate_sql(bad, TABLES)


def test_keywords_inside_strings_are_ok():
    validate_sql("SELECT * FROM CUSTOMERS WHERE CITY = 'DELETE; DROP'", TABLES)


def test_comment_cannot_hide_statement():
    with pytest.raises(SqlRejected):
        validate_sql("SELECT 1 FROM CUSTOMERS -- x\n; DROP TABLE CUSTOMERS", TABLES)


def test_extract_and_cte_and_join_ok():
    validate_sql("SELECT EXTRACT(YEAR FROM ORDER_DATE) AS Y FROM SALES_ORDERS", TABLES)
    validate_sql(
        "WITH t AS (SELECT * FROM SALES_ORDERS) SELECT * FROM t JOIN CUSTOMERS c ON c.CUSTOMER_ID = t.CUSTOMER_ID",
        TABLES,
    )
    validate_sql('SELECT * FROM VTF."SALES_ORDERS"', TABLES)


# ---------- service ----------
def test_generate_sql_happy_path(store):
    p = FakeProvider(
        json.dumps({"sql": "SELECT CITY FROM CUSTOMERS", "explanation": "cities"})
    )
    r = service.generate_sql(p, store, "list customer cities")
    assert r["tables_used"] == ["CUSTOMERS"] and "LIMIT" in r["sql"]


def test_repair_loop_recovers(store):
    p = FakeProvider(
        json.dumps({"sql": "DELETE FROM CUSTOMERS", "explanation": ""}),
        json.dumps({"sql": "SELECT CITY FROM CUSTOMERS", "explanation": "ok"}),
    )
    r = service.generate_sql(p, store, "list customer cities")
    assert p.calls == 2 and r["sql"].startswith("SELECT")


def test_gives_up_after_retries(store):
    bad = json.dumps({"sql": "DROP TABLE X", "explanation": ""})
    with pytest.raises(service.ModelOutputError):
        service.generate_sql(FakeProvider(bad, bad, bad), store, "anything here")


def test_clarifying_question(store):
    p = FakeProvider(
        json.dumps(
            {"sql": None, "explanation": "", "clarifying_question": "Which year?"}
        )
    )
    r = service.generate_sql(p, store, "show sales")
    assert r["sql"] is None and r["clarifying_question"] == "Which year?"


def test_visual_spec_rejects_unknown_column():
    cols = [ColumnInfo(name="MONTH"), ColumnInfo(name="TOTAL")]
    good = json.dumps({"chart_type": "bar", "title": "t", "x": "MONTH", "y": ["TOTAL"]})
    assert (
        service.generate_visual(FakeProvider(good), "sales", cols, "spec")["x"]
        == "MONTH"
    )
    bad = json.dumps({"chart_type": "bar", "x": "NOPE", "y": ["TOTAL"]})
    with pytest.raises(service.ModelOutputError):
        service.generate_visual(FakeProvider(bad), "sales", cols, "spec")


def test_visual_code_blocks_network_calls():
    cols = [ColumnInfo(name="A")]
    with pytest.raises(service.ModelOutputError):
        service.generate_visual(
            FakeProvider("fetch('http://evil')"), "chart", cols, "js"
        )


def test_table_selection_prunes_large_schema():
    tables = [{"name": f"T{i}", "columns": [{"name": "C"}]} for i in range(30)]
    tables.append(
        {"name": "INVOICES", "description": "billing", "columns": [{"name": "AMOUNT"}]}
    )
    store = SchemaStore(SchemaPayload(tables=tables))
    assert store.select_tables("invoices amount", 5)[0].name == "INVOICES"


# ---------- providers ----------
def test_fallback_uses_next_provider_when_first_fails():
    from app.providers import FallbackProvider, ProviderError

    class Broken(LLMProvider):
        name, model = "broken", "b"

        def chat(self, *a, **k):
            raise ProviderError("429 rate limit")

    good = FakeProvider("hello")
    chain = FallbackProvider([Broken(), good])
    assert chain.chat([{"role": "user", "content": "hi"}]) == "hello"
    assert chain.name == "fake" and chain.model == "fake-1"


def test_fallback_raises_when_all_fail():
    from app.providers import FallbackProvider, ProviderError

    class Broken(LLMProvider):
        name, model = "broken", "b"

        def chat(self, *a, **k):
            raise ProviderError("down")

    with pytest.raises(ProviderError):
        FallbackProvider([Broken(), Broken()]).chat([])


def test_auto_skips_providers_without_keys(monkeypatch):
    from app import providers

    for k in ["GEMINI", "GROQ", "OPENROUTER", "OPENAI"]:
        monkeypatch.delenv(f"{k}_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "x")
    chain = providers.get_provider("auto")
    assert [p.name for p in chain.providers] == ["groq", "local"]


def test_parse_json_ignores_think_block():
    out = service._parse_json(
        '<think>maybe {"a": 1}</think>\n{"sql": "SELECT 1", "explanation": "x"}'
    )
    assert out["sql"] == "SELECT 1"
