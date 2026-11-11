"""
Safety net for SQL written by an AI.

NEVER trust model output. This is layer 1 (Python). Your Node `validateReadOnlySql`
is layer 2, and a READ-ONLY database user is layer 3. Keep all three.
"""
import re


class SqlRejected(ValueError):
    """The generated SQL is not allowed. The message is sent back to the model so it can fix it."""


# Statements / keywords that must never appear (checked outside of string literals)
_BLOCKED = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|MERGE|UPSERT|GRANT|REVOKE|"
    r"CALL|EXEC|EXECUTE|COMMIT|ROLLBACK|IMPORT|EXPORT|LOCK|INTO)\b",
    re.I,
)

# One regex that finds: 'strings', "identifiers", -- line comments, /* block comments */
_TOKEN = re.compile(r"('(?:[^']|'')*')|(\"(?:[^\"]|\"\")*\")|(--[^\n]*)|(/\*.*?\*/)", re.S)


def _strip_comments(sql: str) -> str:
    """Remove comments but keep string literals untouched."""
    return _TOKEN.sub(lambda m: " " if (m.group(3) or m.group(4)) else m.group(0), sql)


def _mask(sql: str, mask_identifiers: bool) -> str:
    """Empty out string literals (and optionally "quoted identifiers") so keywords inside them are ignored."""
    def repl(m):
        if m.group(1):
            return "''"
        if m.group(2):
            return '""' if mask_identifiers else m.group(2)
        return " "
    return _TOKEN.sub(repl, sql)


def _check_tables(cleaned: str, allowed_tables: set[str]) -> None:
    text = _mask(cleaned, mask_identifiers=False)
    # EXTRACT(YEAR FROM col) / TRIM(... FROM ...) contain FROM but are not tables
    text = re.sub(r"\b(?:EXTRACT|TRIM|SUBSTRING)\s*\([^()]*\)", " ", text, flags=re.I)

    ctes = {n.strip('"').upper() for n in re.findall(r'(?:\bWITH|,)\s*("?\w+"?)\s+AS\s*\(', text, re.I)}
    pattern = re.compile(r'\b(?:FROM|JOIN)\s+((?:"[^"]+"|\w+)(?:\s*\.\s*(?:"[^"]+"|\w+))?)(?![\w"(])', re.I)

    unknown = []
    for m in pattern.finditer(text):
        parts = re.findall(r'"[^"]+"|\w+', m.group(1))
        table = parts[-1].strip('"').upper()  # ignore any schema prefix
        if table in ctes or table == "DUMMY":
            continue
        if table not in allowed_tables:
            unknown.append(table)
    if unknown:
        raise SqlRejected(f"Unknown table(s): {', '.join(sorted(set(unknown)))}. Use only tables from the schema.")


def validate_sql(sql: str, allowed_tables: set[str] | None = None, max_rows: int = 1000) -> str:
    """Return a cleaned, safe SQL string or raise SqlRejected."""
    if not isinstance(sql, str):
        raise SqlRejected("SQL must be a string")

    cleaned = _strip_comments(sql).strip().rstrip(";").strip()
    if not cleaned:
        raise SqlRejected("SQL is empty")

    masked = _mask(cleaned, mask_identifiers=True)
    if ";" in masked:
        raise SqlRejected("Only one SQL statement is allowed")
    if not re.match(r"(SELECT|WITH)\b", masked, re.I):
        raise SqlRejected("Only SELECT queries (optionally starting with WITH) are allowed")

    blocked = _BLOCKED.search(masked)
    if blocked:
        raise SqlRejected(f"Keyword not allowed: {blocked.group(1).upper()}")

    if allowed_tables is not None:
        _check_tables(cleaned, {t.upper() for t in allowed_tables})

    if not re.search(r"\bLIMIT\b|\bTOP\s+\d+", masked, re.I):
        cleaned += f"\nLIMIT {max_rows}"
    return cleaned
