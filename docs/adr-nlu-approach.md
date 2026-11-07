# ADR: NLU approach (T-18)

**Status:** accepted. **Date:** 2026-11-08.

## Options

1. **Fine-tune a small open model** on labeled queries (GPU, e.g. Modal).
2. **Prompt a hosted LLM** (Groq, `openai/gpt-oss-20b`) with a versioned template, few-shot
   examples and JSON output validated against `ParsedIntent`.
3. **Deterministic rule parser** (`nlu/parser.py`) over a fixed schema and vocabulary.

## Evidence

| | Rules | Hosted LLM (20-query prototype) |
|---|---|---|
| Accuracy on the 133 hand-labeled queries | intent 100%, entity F1 1.00 (optimistic: same author as the labels) | 15 of the 15 answered had the right intent; 13 of 20 exact (2 wrong spellings of a value, 5 rate-limited) |
| Latency | p95 0.13 ms | p50 about 1.1 s, max about 3.1 s |
| Cost | none | free tier; hit 429 rate limits with a large prompt |
| Handles unseen phrasing | limited | better, in principle |
| Deterministic | yes | no |

Detail: `docs/nlu-calibration.md`, `docs/nlu-latency.md`, `docs/nlu-groq-prototype.md`.

## Decision

Use a **hybrid**: the rule parser answers first. The hosted model is consulted only when the
rules return out-of-scope or a confidence under 0.8 (`nlu/hybrid.py`). Model output is accepted
only through `ParsedIntent` validation, and filter values are snapped onto the real vocabulary.
No fine-tuning for now: the labeled set is small (133 rows, one author), the rules already meet
the gates (intent >= 85%, entity F1 >= 0.9), and a GPU would add cost without a measured gain.

## Revisit when

- Real user queries show the rules missing phrasing the hosted model handles (check
  `logs/fallbacks.jsonl`).
- The labeled set grows past a few hundred rows from `confirm/log.py` exports; then fine-tuning
  a small model on that data becomes worth measuring.
