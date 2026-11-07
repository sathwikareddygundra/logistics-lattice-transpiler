# T-17 + T-12 — handoff notes

T-12 explicitly depends on T-17 ("wait until T-17 exists, since the schema
needs to reflect the real intent types"), so both are included here,
built in that order.

## What's here

```
nlu/
  taxonomy.py                    # T-17: IntentType enum + TAXONOMY with 3+
                                  #   grounded examples per category, plus
                                  #   an explicit out_of_scope bucket
schemas/
  parsed_intent.schema.json      # T-12: JSON Schema, draft 2020-12
  validate_parsed_intent.py      # validator (uses `jsonschema` if
                                  #   installed, else a minimal fallback)
  examples/
    valid_aggregation.json
    valid_join_multiplant.json
    valid_out_of_scope.json
    malformed_bad_entity_type.json   # deliberately broken, for the test
tests/
  test_taxonomy.py               # T-17 acceptance test
  test_parsed_intent_schema.py   # T-12 acceptance test
```

## Acceptance criteria, checked off

**T-17** — every intent category has real examples, and every query can be
confidently bucketed (including `out_of_scope`):
`python3 -m unittest tests.test_taxonomy -v`

**T-12** — valid example intents pass validation, and the malformed one
fails with a readable error pointing at what's wrong:
```
$ python3 schemas/validate_parsed_intent.py schemas/examples/*.json
validation engine: jsonschema   # or "minimal fallback" if not installed
PASS  schemas/examples/malformed_bad_entity_type.json  <- would read FAIL
      - $['entities'][1]['entity_type']: 'date' is not one of
        ['table', 'column', 'plant', 'date_range', ...]
```
(Full run of both test files: `python3 -m unittest discover -s tests -v`
— 12 tests, all passing.)

## One thing to do when you merge this into the real repo

This sandbox has no network access, so `schemas/validate_parsed_intent.py`
ships with a small **fallback** validator for keywords the schema actually
uses (type, enum, const, required, additionalProperties, properties,
items, $ref/$defs, minimum/maximum, minLength, format:uuid). It's not a
general JSON Schema implementation — don't lean on it for T-13/T-14/T-15.

In your real repo, per T-2:
```
uv add jsonschema      # or: poetry add jsonschema
```
Once `jsonschema` is importable, `validate_parsed_intent.py` uses the real
`Draft202012Validator` automatically — nothing else to change, and the
existing tests keep passing unmodified.

## Drift guard worth knowing about

`test_intent_enum_matches_taxonomy` compares the schema's `intent_type`
enum against `nlu.taxonomy.allowed_intent_values()` and fails if they
diverge. If T-20 or later work adds a new intent category, update
`nlu/taxonomy.py` first — this test will then tell you exactly where the
schema is now out of sync.

## Next task

T-13 — JSON Schema for DAG nodes and edges — has the same shape of
dependency: it explicitly waits on T-34 (node/edge data model), which is
Phase 5. So the natural next step in dependency order is actually T-16
(finish versioning/breaking-change policy for T-12–T-15) or jumping ahead
into Phase 3 (T-18 onward) to start building the NLU stage that will
actually produce `ParsedIntent` documents — your call on which order suits
you, since both are unblocked from here.
