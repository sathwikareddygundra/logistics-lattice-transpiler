# SQL dialect matrix (T-75)

| Plant | Engine | Version tested | sqlglot dialect | Physical tables |
|---|---|---|---|---|
| MCW | SQLite | 3.53.1 | `sqlite` | `dispatch`, `tracking`, `turnaround_time` |
| YCW | DuckDB | 2.0.0 | `duckdb` | `ycw_dispatch`, `ycw_tracking`, `ycw_tat` |
| VGU | PostgreSQL | 16.15 (local server, `scripts/local_postgres.sh`) | `postgres` | `vgu_dispatch`, `vgu_tracking`, `vgu_tat` |

By default VGU runs on SQLite so the test suite needs no server. Set
`LATTICE_VGU_ENGINE=postgres` and `LATTICE_PG_DSN` (see `scripts/local_postgres.sh`) to run VGU on
PostgreSQL; `tests/test_postgres.py` does this and is skipped when no server is reachable.
CI starts a PostgreSQL 16 service so these tests always run there.

## Divergences from ANSI SQL that the generator handles

| Topic | SQLite | DuckDB | PostgreSQL | Where handled |
|---|---|---|---|---|
| Time bucket (month) | `strftime('%Y-%m', c)` | `strftime(c, '%Y-%m')` | `to_char(c, 'YYYY-MM')` | `cag/templates.py` `bucket.sql.*` |
| Time bucket (quarter) | string concat of year and `(month+2)/3` | `quarter(c)` | `extract(quarter ...)` | same |
| Time bucket (week) | `%W` (Monday-first) | `%W` | hand-built to match `%W` | same (labels agree, tested) |
| Timestamp storage | ISO text | `TIMESTAMP` | `TIMESTAMP` | loader in `plantdb/plants.py` |
| Date comparison with a string literal | text compare | implicit cast | implicit cast | plain `col >= '2026-07-01'` works in all three |
| `SUM(integer)` result | integer | `HUGEINT` | `numeric` (returned as Decimal) | sandbox converts Decimal to float |
| Identifier quoting | `"x"` | `"x"` | `"x"` | `codegen/sql.py` quotes reserved words, or everything with the retry hint |
| Boolean literal | 1/0 | TRUE/FALSE | TRUE/FALSE | `literal()` emits TRUE/FALSE, valid in all three |
| Full outer join | supported (3.39+) | supported | supported | `JOIN_KEYWORDS` |
| Read-only access | `mode=ro` + `query_only` | `read_only=True` | `lattice_ro` role + read-only transactions | `sandbox/runner.py` |
| Statement timeout | progress handler | `interrupt()` timer | `statement_timeout` | same |

Everything not in this table uses constructs that behave the same in all three engines.
