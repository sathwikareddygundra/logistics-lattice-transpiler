"""Thin wrapper client for the Groq API with retry, backoff, and a fixed
timeout budget.

See docs/T-4-compute-decision.md for why Groq was chosen. This is the
general-purpose client referenced by T-5. The confirm-intent step (T-28)
uses its own separate, more tightly-scoped client instance — do not
merge the two.
"""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass

import httpx

# Named constants — not magic numbers, per T-5's done-when condition.
REQUEST_TIMEOUT_SECONDS = 3.0
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 0.5
BACKOFF_JITTER_SECONDS = 0.25

GROQ_API_BASE_URL = "https://api.groq.com/openai/v1"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class GroqClientError(Exception):
    """Raised when a Groq API call fails after exhausting all retries,
    or fails in a way that isn't worth retrying."""


@dataclass
class ChatCompletionResult:
    content: str
    raw_response: dict


class GroqClient:
    """Minimal wrapper around Groq's chat completions endpoint.

    Reads the API key from the GROQ_API_KEY environment variable by
    default — never accepts a hardcoded fallback, so a missing key fails
    loudly instead of silently using a stale or leaked value.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("GROQ_API_KEY")
        if not self._api_key:
            raise GroqClientError(
                "GROQ_API_KEY is not set. Export it in your shell or .env "
                "file — never hardcode it in source."
            )
        self._client = httpx.Client(
            base_url=GROQ_API_BASE_URL,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    def chat_completion(self, model: str, messages: list[dict]) -> ChatCompletionResult:
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                response = self._client.post(
                    "/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={"model": model, "messages": messages},
                )
            except httpx.TimeoutException as exc:
                last_error = exc
                self._sleep_backoff(attempt)
                continue

            if response.status_code == 200:
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                return ChatCompletionResult(content=content, raw_response=data)

            if response.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
                last_error = GroqClientError(
                    f"Groq API returned {response.status_code}, retrying "
                    f"(attempt {attempt + 1}/{MAX_RETRIES})"
                )
                self._sleep_backoff(attempt)
                continue

            raise GroqClientError(
                f"Groq API call failed with status {response.status_code}: {response.text}"
            )

        raise GroqClientError(f"Groq API call failed after {MAX_RETRIES} retries: {last_error}")

    @staticmethod
    def _sleep_backoff(attempt: int) -> None:
        delay = BACKOFF_BASE_SECONDS * (2 ** attempt) + random.uniform(0, BACKOFF_JITTER_SECONDS)
        time.sleep(delay)

    def close(self) -> None:
        self._client.close()
