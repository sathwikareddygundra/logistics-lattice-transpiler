# On-call runbook (T-100)

Written for someone who did not build the system. A *trace_id* is a short code that tags every log line belonging to one question.

**Finding the trace_id.** The service prints its logs to standard output as JSON, one object per line, so capture that output to a file (below it is called `service.log`). A failed question carries a `trace_id`. To see everything that happened to it:

```bash
grep '"trace_id": "<ID>"' service.log
```

Each stage logs its name, duration and whether it succeeded, so the last stage with `ok: false` is where it broke. Inside the running program, `logging_config.get_trace("<ID>")` returns the same journey as a list.

Failures are also written to `logs/failures.jsonl`. That file stores only a shortened hash of the trace_id (so it holds no personal data). To find a row for a trace_id:

```bash
grep "$(printf '%s' '<ID>' | shasum -a 256 | cut -c1-12)" logs/failures.jsonl
```

**Escalation (all categories).** If you cannot resolve it within 30 minutes, or more than one plant is affected, page the engineering owner of the pipeline.

## syntax_error

- **Symptom:** the alert `HighFailureRate` fires and failing questions mention a parse error; generated SQL or Python was rejected before running.
- **Likely causes:** a plant's SQL dialect rule is wrong; a column name needs quoting; a template was changed.
- **Diagnosis:** find the trace_id, open the generated code in the trace, and paste the SQL into the plant's database console to see the error. Check `git log cag/templates.lock.json` for a recent template change.
- **Remediation:** the system retries once with quoted names or switches between SQL and Python. If it keeps failing, revert the template change and redeploy.
- **Escalation:** if it affects every question for a plant, roll that plant back (see the rollout plan).

## semantic_mismatch

- **Symptom:** the answer was blocked because it looked wrong: wrong columns, an impossible plan, or a row count 10x away from the estimate.
- **Likely causes:** a new question shape the planner cannot express; a join dropping rows; stale statistics behind the row estimate.
- **Diagnosis:** with the trace_id, compare the `estimated` and `actual` row counts in the trace and look at the plan stage output.
- **Remediation:** if it is one odd question, nothing to do (the user is told it cannot be answered). If many, roll back the latest change.
- **Escalation:** any `RowCountMismatch` ticket during a rollout blocks that plant from advancing.

## intent_mismatch

- **Symptom:** users say the system answered a different question than they asked, or reports "not supported" for sensible questions.
- **Likely causes:** new wording the parser has not seen; a new plant, table or column name not in the vocabulary.
- **Diagnosis:** find the trace_id and read the parsed intent in the trace. Compare it with the question.
- **Remediation:** add the wording to `nlu/data/labeled_queries.jsonl` and the vocabulary, then run the tests. Users can answer the confirm question to correct the system in the meantime.
- **Escalation:** rising `lattice_confirm_triggered_total` with rising complaints means the parser needs retraining or fixing; raise a ticket with 10 example questions.

## timeout

- **Symptom:** questions fail after a long wait; the `SlowStage` alert fires or the language-model service errors.
- **Likely causes:** a very large date range; the database is busy; the Groq language-model service is slow or down.
- **Diagnosis:** with the trace_id, find the slowest stage and its duration. For Groq problems check the provider status page and look for `GroqClientError`.
- **Remediation:** retry later for provider issues (the rule-based parser still handles most questions without it). For a slow database, ask the owner to check load.
- **Escalation:** if the database itself is unresponsive, contact the database owner.

## resource_limit

- **Symptom:** the user sees that the result was cut off or too large.
- **Likely causes:** a question without filters returning more than the row cap.
- **Diagnosis:** find the trace_id; the trace shows the row cap being hit.
- **Remediation:** tell the user to narrow the question (a date range, one plant). Do not raise the cap to fix one question.
- **Escalation:** only if many users hit it; a ticket to revisit the cap.

## permission

- **Symptom:** failures say a forbidden operation was blocked or that the database cannot be reached.
- **Likely causes:** generated code tried to write or delete (blocked on purpose); the read-only database login stopped working; the database file or server is missing.
- **Diagnosis:** the trace shows `DatabaseUnavailableError` or the blocked statement. Check the database is up (for PostgreSQL: `scripts/local_postgres.sh status`) and that the read-only login still works.
- **Remediation:** restore the database or the login. Never grant write access to make an error go away.
- **Escalation:** a blocked write attempt that you cannot explain is a security matter; tell the security contact.

## schema_drift

- **Symptom:** the `SchemaDriftFailures` or `SchemaDrift` alert; queries fail saying a column or table no longer matches.
- **Likely causes:** someone changed a plant's tables (added, renamed or retyped a column) without updating the catalog.
- **Diagnosis:** compare fingerprints with `ops.drift.schema_fingerprint` for production and staging, then `check_drift` lists the added, removed and changed columns.
- **Remediation:** update `plantdb/catalog.py` and regenerate the inventory with `scripts/build_inventory.py`, then run the tests. If the change was a mistake, ask the database owner to revert it.
- **Escalation:** pause the rollout of any plant with drift until it is resolved.
