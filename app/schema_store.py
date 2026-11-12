"""
Holds table/column names + descriptions (NO data) and decides which part of the
schema to put in the prompt. Small local models have small context windows, so we
send only the most relevant tables instead of everything.
"""

import json
import re
from pathlib import Path

from .models import SchemaPayload

_WORD = re.compile(r"[a-z0-9]+")


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower().replace("_", " ")))


class SchemaStore:
    def __init__(self, payload: SchemaPayload, examples: list[dict] | None = None):
        self.payload = payload
        self.examples = examples or []

    # ---------- loading ----------
    @classmethod
    def from_files(
        cls, schema_file: str, examples_file: str | None = None
    ) -> "SchemaStore":
        payload = SchemaPayload.model_validate(
            json.loads(Path(schema_file).read_text(encoding="utf-8"))
        )
        examples = []
        if examples_file and Path(examples_file).exists():
            examples = json.loads(Path(examples_file).read_text(encoding="utf-8"))
        return cls(payload, examples)

    def with_schema(self, payload: SchemaPayload) -> "SchemaStore":
        """Same examples, different (live) schema sent by the caller."""
        return SchemaStore(payload, self.examples)

    # ---------- lookups ----------
    def table_names(self) -> set[str]:
        return {t.name.upper() for t in self.payload.tables}

    def select_tables(self, text: str, limit: int) -> list:
        tables = self.payload.tables
        if len(tables) <= limit:
            return tables

        q = _words(text)
        for (
            term,
            meaning,
        ) in self.payload.glossary.items():  # expand "GRN" -> "goods receipt note"
            if term.lower() in q:
                q |= _words(meaning)

        def score(table) -> int:
            s = 3 * len(q & _words(table.name))
            s += 2 * len(q & _words(table.description))
            for col in table.columns:
                s += len(q & _words(col.name)) + len(q & _words(col.description))
            return s

        ranked = sorted(tables, key=score, reverse=True)
        return ranked[:limit]

    def select_examples(
        self, question: str, k: int = 3, max_chars: int = 2500
    ) -> list[dict]:
        q = _words(question)
        pool = [
            e for e in self.examples if len(e["sql"]) <= max_chars
        ]  # huge queries waste the prompt
        ranked = sorted(
            pool, key=lambda e: len(q & _words(e["question"])), reverse=True
        )
        return [e for e in ranked[:k] if q & _words(e["question"])]

    # ---------- prompt text ----------
    def describe(self, tables: list) -> str:
        lines = []
        for t in tables:
            lines.append(
                f"TABLE {t.name}" + (f"  -- {t.description}" if t.description else "")
            )
            for c in t.columns:
                lines.append(
                    f"  {c.name} ({c.type})"
                    + (f"  -- {c.description}" if c.description else "")
                )
        return "\n".join(lines)

    def describe_rules(self) -> str:
        return "\n".join(f"- {r}" for r in self.payload.rules)

    def describe_glossary(self) -> str:
        return "\n".join(f"{k} = {v}" for k, v in self.payload.glossary.items())
