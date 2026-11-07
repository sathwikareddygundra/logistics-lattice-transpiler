"""LLM-backed parser: asks Groq for a JSON intent and validates it (T-18, T-22, T-23).

The prompt template and the few-shot examples are version-controlled files.
Model output is accepted only through ParsedIntent validation, so free text
can never leak downstream.
"""

from __future__ import annotations

import difflib
import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from common.groq_client import GroqClient
from nlu.intent import ParsedIntent
from plantdb.vocab import column_values

MODEL = "openai/gpt-oss-20b"
PROMPT_VERSION = "v1"
EXAMPLES_PER_INTENT = 1
_HERE = Path(__file__).parent


class GroqParseError(ValueError):
    pass


@lru_cache(maxsize=1)
def _template() -> str:
    return (_HERE / "prompts" / f"parse_intent.{PROMPT_VERSION}.txt").read_text()


@lru_cache(maxsize=1)
def _fewshot() -> dict[str, list[dict]]:
    return json.loads((_HERE / "fewshot.json").read_text())


def build_system_prompt(today: date) -> str:
    lines = []
    for intent in sorted(_fewshot()):
        for ex in _fewshot()[intent][:EXAMPLES_PER_INTENT]:
            lines.append(f"Q: {ex['query']}\nA: {json.dumps(ex['output'], sort_keys=True)}")
    values = "\n".join(f"- {c}: {', '.join(v)}" for c, v in sorted(column_values().items()))
    return _template().format(today=today.isoformat(), examples="\n".join(lines), values=values)


def canonicalize(intent: ParsedIntent) -> ParsedIntent:
    """Snap model-written filter values onto the real vocabulary ("Atlanta" -> "Atlanta_WH")."""
    vocab = column_values()
    fixed = []
    for f in intent.filters:
        values = vocab.get(f.column)
        if values and isinstance(f.value, str) and f.value not in values:
            match = difflib.get_close_matches(f.value, values, n=1, cutoff=0.6)
            if not match:
                lowered = {v.lower().split("_")[0]: v for v in values}
                key = f.value.lower().split("_")[0]
                match = [lowered[key]] if key in lowered else []
            if match:
                f = f.model_copy(update={"value": match[0]})
        fixed.append(f)
    return intent.model_copy(update={"filters": fixed})


def parse_with_groq(query: str, client: GroqClient, today: date | None = None) -> ParsedIntent:
    result = client.chat_completion(
        MODEL,
        [
            {"role": "system", "content": build_system_prompt(today or date.today())},
            {"role": "user", "content": query},
        ],
        extra={"response_format": {"type": "json_object"}},
    )
    text = result.content.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(text)
        data["query"] = query
        data.setdefault("confidence", 0.0)
        return canonicalize(ParsedIntent.model_validate(data))
    except (json.JSONDecodeError, ValueError) as exc:
        raise GroqParseError(f"model returned an unusable intent: {exc}") from exc
