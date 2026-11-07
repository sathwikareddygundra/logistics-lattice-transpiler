# NLU latency and SLA (T-26)

500 queries through the rule parser on macOS-15.7.9-arm64-arm-64bit (arm64), Python 3.11.16.

- p50 0.110 ms
- p95 0.131 ms
- p99 0.167 ms

## SLA

- Rule parser: p95 under 50 ms (enforced by tests/test_nlu_latency.py).
- Hosted-model path (Groq): p95 under 3 s per parse; measured latency in
  docs/nlu-groq-prototype.md. The confirm client's own timeout is budgeted inside this.
