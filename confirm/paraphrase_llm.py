"""Optional LLM rewording of the template paraphrase, with a hard fallback to the template."""

from __future__ import annotations

import json

from common.groq_client import GroqClient, GroqClientError
from confirm.router import paraphrase
from nlu.intent import ParsedIntent

MODEL = "openai/gpt-oss-20b"
MAX_CHARS = 300


def llm_paraphrase(intent: ParsedIntent, client: GroqClient) -> str:
    template = paraphrase(intent)
    try:
        result = client.chat_completion(
            MODEL,
            [
                {
                    "role": "system",
                    "content": "Reword this question-understanding sentence in plain, friendly "
                    "English in one sentence ending with a question mark. Do not add or drop any "
                    "condition. Reply with the sentence only.",
                },
                {
                    "role": "user",
                    "content": template
                    + "\n"
                    + json.dumps(intent.model_dump(mode="json", exclude_defaults=True)),
                },
            ],
        )
    except GroqClientError:
        return template
    text = result.content.strip()
    return text if 0 < len(text) <= MAX_CHARS and text.endswith("?") else template
