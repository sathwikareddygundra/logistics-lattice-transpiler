"""LLM-backed parser: asks Groq for a JSON intent and validates it.

The model output is only ever accepted through ParsedIntent validation, so
free text can never leak downstream.
"""

from __future__ import annotations

import json

from common.groq_client import GroqClient
from nlu.intent import ParsedIntent
from plantdb.catalog import DISPATCH

MODEL = "openai/gpt-oss-20b"

_SYSTEM = f"""You convert logistics questions into a JSON intent. Reply with JSON only.
Table: dispatch. Columns: {", ".join(DISPATCH.columns)}.
Fields: intent_type (aggregation|rank|out_of_scope), table, metric (column), agg
(sum|count|avg|min|max), group_by (list of columns), filters (list of
{{column, operator: eq|ne|gt|gte|lt|lte, value}}), sort_direction (asc|desc|null),
limit (int|null), confidence (0-1). Dates are ISO strings (YYYY-MM-DD).
Use out_of_scope with confidence 0 for anything not answerable from this table."""


class GroqParseError(ValueError):
    pass


def parse_with_groq(query: str, client: GroqClient) -> ParsedIntent:
    result = client.chat_completion(
        MODEL,
        [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": query}],
    )
    text = result.content.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(text)
        data["query"] = query
        return ParsedIntent.model_validate(data)
    except (json.JSONDecodeError, ValueError) as exc:
        raise GroqParseError(f"model returned an unusable intent: {exc}") from exc
