"""
Builds schema/examples.json (question -> SQL pairs) from your working queries.

python tools/build_examples.py --queries queries.json [--strip-schema VISHAL_LIVE] [--out schema/examples.json]

Kept: short, read-only, readable queries. Date parameters (?) become sample literal dates.
Skipped: huge queries, {{placeholders}}, stored procedures, queries that need non-date parameters.
Examples you added by hand (entries without "source") are preserved.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.sql_guard import SqlRejected, _strip_comments, validate_sql  # noqa: E402

JUNK = {"", "explain", "query description", "test query"}
STR_RE = re.compile(r"('(?:[^']|'')*')")


def literal_for(name: str):
    n = name.lower().replace(" ", "")
    if "date" in n:
        if "from" in n:
            return "'2025-04-01'"
        return "'2026-03-31'"
    if "days" in n:
        return "30"
    if "months" in n:
        return "3"
    return None


def fill_params(sql: str, names: list[str]):
    """Replace each ? (outside strings) with a sample literal. Returns None if impossible."""
    parts = STR_RE.split(sql)
    k = 0
    for i in range(0, len(parts), 2):  # even parts are outside string literals

        def repl(_):
            nonlocal k
            if k >= len(names):
                raise IndexError
            lit = literal_for(names[k])
            k += 1
            if lit is None:
                raise ValueError
            return lit

        try:
            parts[i] = re.sub(r"\?", repl, parts[i])
        except (IndexError, ValueError):
            return None
    return "".join(parts)  # extra names (e.g. a stray "limit") are ignored


def tidy(sql: str, strip_schema: str | None) -> str:
    sql = _strip_comments(sql)
    if strip_schema:
        sql = re.sub(rf'"?{re.escape(strip_schema)}"?\s*\.\s*', "", sql, flags=re.I)
    sql = re.sub(r"[ \t]+\n", "\n", sql)
    sql = re.sub(r"\n\s*\n+", "\n", sql)
    return sql.strip().rstrip(";").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", required=True)
    ap.add_argument("--out", default="schema/examples.json")
    ap.add_argument(
        "--strip-schema",
        default=None,
        help="schema name hard-coded in some queries, e.g. VISHAL_LIVE",
    )
    ap.add_argument("--max-chars", type=int, default=2500)
    args = ap.parse_args()

    queries = json.loads(Path(args.queries).read_text(encoding="utf-8"))
    out_path = Path(args.out)
    manual = []
    if out_path.exists():
        manual = [
            e
            for e in json.loads(out_path.read_text(encoding="utf-8"))
            if not e.get("source")
        ]

    examples, seen, skipped = [], set(), {}
    for q in queries:
        qid, desc, sql = (
            q.get("id", "?"),
            (q.get("description") or "").strip(),
            (q.get("sql") or ""),
        )
        reason = None
        if desc.lower() in JUNK or len(desc) < 6:
            reason = "no description"
        elif not sql.strip() or "{{" in sql or sql.strip().upper().startswith("CALL"):
            reason = "empty / placeholder / procedure"
        elif desc.lower() in seen:
            reason = "duplicate description"
        else:
            sql = tidy(sql, args.strip_schema)
            if "?" in sql:
                sql = fill_params(sql, q.get("paramNames") or [])
                if sql is None:
                    reason = "needs non-date parameters"
            if sql is not None and reason is None:
                if len(sql) > args.max_chars:
                    reason = "too long"
                else:
                    try:
                        validate_sql(sql, None)
                    except SqlRejected:
                        reason = "not a plain SELECT"
        if reason:
            skipped.setdefault(reason, []).append(qid)
            continue
        seen.add(desc.lower())
        examples.append({"question": desc, "sql": sql, "source": qid})

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(manual + examples, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"wrote {out_path}: {len(examples)} generated + {len(manual)} manual examples"
    )
    for reason, ids in skipped.items():
        print(f"  skipped {len(ids):3d}  {reason}")


if __name__ == "__main__":
    main()
