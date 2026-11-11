# T-16: schema versioning & breaking-change policy

Covers the four wire contracts built so far: `parsed_intent.schema.json`
(T-12), `dag.schema.json` (T-13), `ir.schema.json` (T-14), and
`ast.schema.json` (T-15). Every one already carries a required
`schema_version` string, pinned with `"const"` to an exact
`MAJOR.MINOR.PATCH` value -- `tests/test_schema_versions.py` enforces
this on every `schemas/*.schema.json` file, so a new schema without a
version fails CI automatically instead of getting forgotten.

## Why `const`, not a loose string

Every schema currently pins `schema_version` to one exact value rather
than accepting a range. That's deliberate: a producer and consumer built
against different versions should fail loudly and immediately (wrong
`const`), not silently accept a document shaped differently than the
code expects. The cost is that producer and consumer must upgrade
together on any version bump -- there's no gradual rollout across
versions yet. If independent stage rollout ever becomes a real
requirement (see T-97's canary plan), revisit this by widening
`schema_version` to an `enum` of supported versions instead of a single
`const`, and add per-version branches to each validator.

## What counts as what

**PATCH** (`1.0.0` -> `1.0.1`) -- no shape change at all. Fixing a
`description` string, clarifying a validator's error message, adding an
example file. A document valid under the old patch version is valid
under the new one and vice versa.

**MINOR** (`1.0.0` -> `1.1.0`) -- backward-compatible and additive
only. Every document that validated before still validates after.
Examples: adding a new optional property; adding a new enum value that
old consumers simply won't produce yet (e.g. a new `node_type` in
`dag.schema.json`, or a new `intent_type` in `parsed_intent.schema.json`
alongside its taxonomy entry); relaxing a constraint (widening an enum,
dropping something from `required`).

**MAJOR** (`1.0.0` -> `2.0.0`) -- anything that can make a previously
valid document invalid. Examples: removing or renaming a required
field; adding a new required field; narrowing an enum (removing a
value); changing a field's type; tightening a constraint (`minLength`,
`minimum`, etc.) beyond what existing documents already satisfy.

When in doubt, ask: "does at least one currently-valid example document
in `schemas/examples/` stop validating?" If yes, it's MAJOR.

## Migration process for a MAJOR bump

1. Bump the `const` in the schema file to the new version.
2. Update every drift-guard test that compares the schema's enum against
   its source-of-truth Python model (`test_intent_enum_matches_taxonomy`,
   `test_node_type_enum_matches_model`, `test_op_enum_matches_grammar`,
   `test_op_enum_matches_nodes`) if the bump touches that enum.
3. Update `schemas/examples/*.json` to the new shape -- old examples
   should either be updated in place or deleted, not left silently
   failing.
4. Update every producer and consumer of that document shape in the same
   change (or the same short-lived branch sequence) -- per the `const`
   design above, there's no window where old and new versions coexist.
5. Note the change in this file's changelog below.

## Changelog

| Schema | Version | Change |
|---|---|---|
| `parsed_intent.schema.json` | 1.0.0 | Initial (T-12) |
| `dag.schema.json` | 1.0.0 | Initial (T-13) |
| `ir.schema.json` | 1.0.0 | Initial (T-14) |
| `ast.schema.json` | 1.0.0 | Initial (T-15) |
