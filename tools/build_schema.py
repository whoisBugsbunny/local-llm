"""
Builds schema/schema.json from your working queries (and optionally your live HANA schema).

python tools/build_schema.py --queries queries.json [--hana hana_schema.json] [--out schema/schema.json]

* Only tables you really use are included, and only columns you really use (keeps prompts small).
* With --hana, column names/types are checked against the real database (recommended).
* Descriptions you wrote by hand in an existing schema.json are never overwritten.
"""

import argparse
import json
import sys
from collections import Counter
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sap_knowledge import COLUMN_DESC, GLOSSARY, RULES, TABLE_DESC  # noqa: E402
from sql_scan import scan_all  # noqa: E402

KEY_COLUMNS = [
    "DocEntry",
    "DocNum",
    "DocDate",
    "CardCode",
    "CardName",
    "ItemCode",
    "LineNum",
    "CANCELED",
    "DocStatus",
]


def collect_sql(queries: list[dict]) -> list[str]:
    sqls = []
    for q in queries:
        if isinstance(q.get("sql"), str) and q["sql"].strip():
            sqls.append(q["sql"])
        for pre in q.get("preParams") or []:
            if isinstance(pre.get("sql"), str):
                sqls.append(pre["sql"])
    return sqls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", required=True)
    ap.add_argument("--hana")
    ap.add_argument("--out", default="schema/schema.json")
    ap.add_argument("--schema-name", default="VTF")
    ap.add_argument(
        "--max-cols", type=int, default=60, help="max columns kept per table"
    )
    args = ap.parse_args()

    queries = json.loads(Path(args.queries).read_text(encoding="utf-8"))
    table_uses, table_cols = scan_all(collect_sql(queries))

    real: dict[str, dict[str, str]] = {}  # TABLE -> {COLUMN_UPPER: (Name, type)}
    if args.hana:
        data = json.loads(Path(args.hana).read_text(encoding="utf-8"))
        for t in data.get("tables", []):
            real[t["name"].upper()] = {
                c["name"].upper(): (c["name"], c.get("type", "unknown"))
                for c in t.get("cols", [])
            }

    out_path = Path(args.out)
    old = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    old_tables = {t["name"].upper(): t for t in old.get("tables", [])}

    tables, missing_in_hana, undescribed = [], [], []
    for table, uses in table_uses.most_common():
        used = table_cols.get(table) or Counter()
        cols: list[tuple[str, str]] = []  # (name, type)
        if real:
            if table not in real:
                missing_in_hana.append(table)
                continue
            wanted = [c for c, _ in used.most_common() if c.upper() in real[table]]
            wanted += [
                k for k in KEY_COLUMNS if k.upper() in real[table] and k not in wanted
            ]
            seen = set()
            for c in wanted:
                name, typ = real[table][c.upper()]
                if name not in seen:
                    seen.add(name)
                    cols.append((name, typ))
        else:
            cols = [(c, "unknown") for c, _ in used.most_common()]
        cols = cols[: args.max_cols]
        if not cols:
            continue

        prev = old_tables.get(table, {})
        prev_cols = {
            c["name"]: c.get("description", "") for c in prev.get("columns", [])
        }
        desc = prev.get("description") or TABLE_DESC.get(table, "")
        if not desc:
            undescribed.append(table)
        tables.append(
            {
                "name": table,
                "description": desc,
                "columns": [
                    {
                        "name": n,
                        "type": t,
                        "description": prev_cols.get(n) or COLUMN_DESC.get(n, ""),
                    }
                    for n, t in cols
                ],
            }
        )

    schema = {
        "schema_name": args.schema_name,
        "glossary": old.get("glossary") or GLOSSARY,
        "rules": old.get("rules") or RULES,
        "tables": tables,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(
        f"wrote {out_path}: {len(tables)} tables, {sum(len(t['columns']) for t in tables)} columns"
    )
    if missing_in_hana:
        print(f"not found in HANA schema (skipped): {', '.join(missing_in_hana)}")
    if undescribed:
        print(
            f"tables WITHOUT description (please add one line each): {', '.join(undescribed)}"
        )


if __name__ == "__main__":
    main()
