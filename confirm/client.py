"""Dedicated Groq client for the confirm step (T-28).

Separate from the general client: tighter timeout and a single retry so the
whole confirm step fits inside the SLA written in docs/nlu-latency.md.
"""

from __future__ import annotations

from common.groq_client import BACKOFF_BASE_SECONDS, BACKOFF_JITTER_SECONDS, GroqClient

CONFIRM_TIMEOUT_SECONDS = 1.0
CONFIRM_MAX_RETRIES = 1
HOSTED_PATH_SLA_SECONDS = 3.0  # p95 budget for NLU + confirm on the hosted-model path
RULE_NLU_P95_SECONDS = 0.05  # rule parser SLA, tests/test_nlu_latency.py


def worst_case_seconds() -> float:
    """Longest the confirm client can spend: every attempt times out, plus backoff."""
    attempts = CONFIRM_MAX_RETRIES + 1
    backoff = sum(
        BACKOFF_BASE_SECONDS * 2**i + BACKOFF_JITTER_SECONDS for i in range(CONFIRM_MAX_RETRIES)
    )
    return attempts * CONFIRM_TIMEOUT_SECONDS + backoff


def make_confirm_client(api_key: str | None = None) -> GroqClient:
    return GroqClient(api_key, timeout=CONFIRM_TIMEOUT_SECONDS, max_retries=CONFIRM_MAX_RETRIES)
