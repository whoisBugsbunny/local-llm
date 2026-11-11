"""All prompt text lives here, so you can tune the AI without touching logic."""

SQL_SYSTEM = """You are a SQL expert for SAP HANA. Turn the user's question into ONE read-only query.

Rules:
- Use ONLY the tables and columns listed in the schema. Never invent names.
- Do not put a schema name in front of tables; the application sets the schema.
- Only SELECT (or WITH ... SELECT). One statement, no semicolon. Never write data-changing or DDL statements.
- Use SAP HANA functions (ADD_DAYS, ADD_MONTHS, TO_DATE, TO_VARCHAR, CURRENT_DATE, YEAR(), MONTH(), IFNULL, LIMIT n).
- Give aggregates readable aliases. Add ORDER BY for rankings / top-N / time series.
- If the question is ambiguous or cannot be answered from the schema, set "sql" to null and ask one short clarifying question.

Reply with JSON only, in exactly this shape:
{"sql": "<query or null>", "explanation": "<one or two plain sentences>", "clarifying_question": "<question or null>"}"""


def build_sql_user_message(store, tables, question: str, previous_sql: str | None) -> str:
    parts = ["SCHEMA:\n" + store.describe(tables)]
    glossary = store.describe_glossary()
    if glossary:
        parts.append("GLOSSARY:\n" + glossary)
    examples = store.select_examples(question)
    if examples:
        parts.append("EXAMPLES:\n" + "\n\n".join(f"Q: {e['question']}\nSQL:\n{e['sql']}" for e in examples))
    if previous_sql:
        parts.append("PREVIOUS QUERY (the user may want a change to this one):\n" + previous_sql)
    parts.append("QUESTION:\n" + question)
    return "\n\n".join(parts)


def build_fix_message(store, tables, sql: str, error: str, question: str | None) -> str:
    parts = ["SCHEMA:\n" + store.describe(tables)]
    if question:
        parts.append("ORIGINAL QUESTION:\n" + question)
    parts.append("THIS QUERY FAILED:\n" + sql)
    parts.append("DATABASE ERROR:\n" + error)
    parts.append("Return a corrected query in the same JSON format.")
    return "\n\n".join(parts)


# ---------------- visuals ----------------
_VISUAL_COMMON = """You build visualizations for a business report.
You will NOT see any data. You only know the column names and types of the query result.
Rules: never fetch from the network, never use eval, cookies, or storage. Use only the listed column names."""

VISUAL_SYSTEM = {
    "spec": _VISUAL_COMMON + """
Return JSON only:
{"chart_type": "bar|line|area|pie|table|kpi", "title": "...", "x": "<column or null>", "y": ["<numeric column>", ...], "notes": "..."}
Pick the chart that best fits the request. "x" and every "y" must be column names from the list.""",

    "tsx": _VISUAL_COMMON + """
Return ONLY the code of one React + TypeScript component, no explanation, no markdown fences.
Use: `export default function Visual({ rows }: { rows: Record<string, any>[] })`
You may import from "react" and "recharts" only. Handle empty rows gracefully.""",

    "html": _VISUAL_COMMON + """
Return ONLY one self-contained HTML document (inline CSS and JS, no external scripts), no markdown fences.
The page receives data with: window.addEventListener('message', e => { const rows = e.data.rows; ... })
Draw the chart with inline SVG or canvas. Show a "no data" message when rows is empty.""",

    "js": _VISUAL_COMMON + """
Return ONLY plain JavaScript defining: function render(container, rows) { ... }
`container` is a DOM element, `rows` is an array of objects. Draw using inline SVG or canvas inside container.""",
}


def build_visual_message(question: str, columns) -> str:
    cols = "\n".join(f"- {c.name} ({c.type})" for c in columns)
    return f"USER REQUEST:\n{question}\n\nRESULT COLUMNS:\n{cols}"


# ---------------- chat ----------------
CHAT_SYSTEM = """You are a friendly internal assistant for a company reporting tool.
Answer simple questions briefly. If the user wants data or a report, tell them to describe the report
they need (you do not run queries in this chat). Never claim to have seen real data."""
