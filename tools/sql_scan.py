"""Reads your existing SQL and finds which tables and columns you really use."""

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.sql_guard import _strip_comments  # noqa: E402

IDENT = r'(?:"[^"]+"|[\w@]+)'
FROM_RE = re.compile(rf"\b(?:FROM|JOIN)\s+({IDENT}(?:\s*\.\s*{IDENT})?)", re.I)
ALIAS_RE = re.compile(r"\s+(?:AS\s+)?([A-Za-z_]\w*)", re.I)
COL_RE = re.compile(r'\b([A-Za-z_]\w*)\s*\.\s*"([^"]+)"')
CTE_RE = re.compile(r'(?:\bWITH|,)\s*("?\w+"?)\s+AS\s*\(', re.I)
NOT_ALIAS = {
    "ON",
    "WHERE",
    "INNER",
    "LEFT",
    "RIGHT",
    "FULL",
    "OUTER",
    "JOIN",
    "CROSS",
    "GROUP",
    "ORDER",
    "UNION",
    "HAVING",
    "LIMIT",
    "AND",
    "OR",
    "SET",
    "USING",
    "WITH",
    "SELECT",
    "FROM",
    "AS",
    "WHEN",
    "THEN",
    "ELSE",
    "END",
}


def _clean(sql: str) -> str:
    sql = re.sub(r"\{\{\w+\}\}", "1=1", sql)  # {{ITMSGRPCOD}} placeholders
    sql = _strip_comments(sql)
    sql = re.sub(r"'(?:[^']|'')*'", "''", sql)  # string literals
    return re.sub(r"\b(?:EXTRACT|TRIM|SUBSTRING)\s*\([^()]*\)", " ", sql, flags=re.I)


def scan_query(sql: str):
    """Returns (set of tables, {table: Counter(columns)})."""
    text = _clean(sql)
    ctes = {c.strip('"').upper() for c in CTE_RE.findall(text)}
    alias_map: dict[str, set[str]] = defaultdict(set)
    tables: set[str] = set()

    for m in FROM_RE.finditer(text):
        end = m.end()
        if (
            text[end:].lstrip().startswith("(")
        ):  # function call, e.g. SERIES_GENERATE_DATE(
            continue
        parts = re.findall(r'"[^"]+"|[\w@]+', m.group(1))
        table = parts[-1].strip('"').upper()
        if table in ctes or table in {"DUMMY", "SELECT"}:
            continue
        tables.add(table)
        alias_map[table].add(table)
        a = ALIAS_RE.match(text, end)
        if a and a.group(1).upper() not in NOT_ALIAS:
            alias_map[a.group(1).upper()].add(table)

    cols: dict[str, Counter] = defaultdict(Counter)
    for alias, col in COL_RE.findall(text):
        for table in alias_map.get(alias.upper(), ()):
            cols[table][col] += 1
    return tables, cols


def scan_all(sqls: list[str]):
    table_uses: Counter = Counter()
    table_cols: dict[str, Counter] = defaultdict(Counter)
    for sql in sqls:
        tables, cols = scan_query(sql)
        table_uses.update(tables)
        for t, c in cols.items():
            table_cols[t].update(c)
    return table_uses, table_cols
