"""LLM-backed parser: asks Groq for a JSON intent and validates it (T-18, T-22, T-23).

The prompt template and the few-shot examples are version-controlled files.
Model output is accepted only through ParsedIntent validation, so free text
can never leak downstream.
"""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from common.groq_client import GroqClient
from nlu.intent import ParsedIntent

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
    return _template().format(today=today.isoformat(), examples="\n".join(lines))


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
        return ParsedIntent.model_validate(data)
    except (json.JSONDecodeError, ValueError) as exc:
        raise GroqParseError(f"model returned an unusable intent: {exc}") from exc
