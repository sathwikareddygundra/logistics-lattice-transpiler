"""Fine-tuned NLU: the LoRA-tuned Qwen3-4B (finetune/train_modal.py) turns the question into a
ParsedIntent. The model call is injected, so tests need no GPU. Output is accepted only through
ParsedIntent validation; any failure falls back to the rule parser."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from nlu.groq_parser import canonicalize
from nlu.intent import ParsedIntent
from nlu.parser import parse

# The training targets omit confidence, so the wrapper sets it: a valid, schema-checked reply
# from the tuned model is treated as confident (it scored 97.8% intent accuracy on held-out
# phrasings), which keeps the confirm step for genuinely ambiguous questions only.
TUNED_CONFIDENCE = 0.9

Generate = Callable[[list[dict]], str]  # [system, user] messages -> raw model text


@dataclass(frozen=True)
class TunedResult:
    intent: ParsedIntent
    source: str  # tuned | rules (tuned unavailable)


def _messages(query: str, today: date) -> list[dict]:
    from finetune.build_dataset import system_prompt

    return [
        {"role": "system", "content": system_prompt(today)},
        {"role": "user", "content": query},
    ]


def parse_tuned(query: str, generate: Generate, today: date | None = None) -> TunedResult:
    today = today or date.today()
    try:
        text = generate(_messages(query, today)).strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        data = json.loads(text)
        data["query"] = query
        data["confidence"] = TUNED_CONFIDENCE
        return TunedResult(canonicalize(ParsedIntent.model_validate(data)), "tuned")
    except Exception:  # unreachable endpoint, bad JSON or schema miss: rules still answer
        return TunedResult(parse(query, today), "rules (tuned unavailable)")


def modal_generate(app_name: str = "lattice-finetune-serve") -> Generate:
    """Call the deployed Modal endpoint (see finetune/serve_modal.py). Needs the `modal` package."""
    import modal

    fn = modal.Cls.from_name(app_name, "Tuned")()

    def generate(messages: list[dict]) -> str:
        return fn.generate.remote(messages)

    return generate
