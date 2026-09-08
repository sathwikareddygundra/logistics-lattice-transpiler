# T-4: NLU compute decision

**Decision:** Hosted LLM API (Groq), not self-hosted/fine-tuned.

**Why:** No GPU provisioning or fine-tuning overhead needed. Matches the
architecture assumed by T-5 (Groq API client), T-18 (NLU approach), and
T-28 (Groq client for the confirm-intent step).

**Model used for verification:** openai/gpt-oss-20b (chosen for
tools/json_mode/structured_outputs support, relevant to T-22's structured
output requirement). Final model choice for production NLU parsing will
be revisited in T-18.

**Verified:** Hello-world inference call via /openai/v1/chat/completions
returned a successful response with content "Hello".
