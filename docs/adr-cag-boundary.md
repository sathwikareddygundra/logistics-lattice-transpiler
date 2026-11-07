# ADR: CAG boundary (T-48)

**Status:** accepted.

CAG ("context assembly") is a **lookup and template-injection layer only**. Zero generative
model calls happen inside it, now or later.

## What CAG does (`cag/`)

- Looks up only the schema slice a node touches (`cag.context.needed_columns`).
- Holds the versioned code-template library and picks exactly one template per node
  (`cag.templates.select_template`; no match raises, nothing falls back silently).
- Assembles both into a context object with a pure function (`assemble_context`): same DAG in,
  byte-identical context out.
- Caches by (schema version, DAG signature, template versions).

## Where CAG ends

CAG retrieves and assembles. **Generation** happens in `codegen/` (AST to SQL or Python), which
renders the selected templates. The model-backed stages are NLU and the optional confirm
paraphrase; everything from the DAG onward is deterministic.

## How the claim is enforced

- `tests/test_cag.py` monkeypatches the Groq client to raise if called during assembly.
- The same input run 100 times must give identical output.
