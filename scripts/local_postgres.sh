#!/usr/bin/env bash
# Starts a project-local PostgreSQL 16 on port 5433 (data in .local/pg, git-ignored).
# Usage: scripts/local_postgres.sh start|stop|status
set -euo pipefail
export LC_ALL="${LC_ALL:-en_US.UTF-8}"
PGBIN="${PGBIN:-/opt/homebrew/opt/postgresql@16/bin}"
DIR="$(cd "$(dirname "$0")/.." && pwd)/.local"
case "${1:-start}" in
  start)
    mkdir -p "$DIR"
    [ -d "$DIR/pg" ] || "$PGBIN/initdb" -D "$DIR/pg" --auth=trust -U postgres >/dev/null
    "$PGBIN/pg_ctl" -D "$DIR/pg" -o "-p 5433 -c listen_addresses=localhost" -l "$DIR/pg.log" -w start || true
    "$PGBIN/psql" -h localhost -p 5433 -U postgres -tc "SELECT 1 FROM pg_database WHERE datname='lattice'" \
      | grep -q 1 || "$PGBIN/createdb" -h localhost -p 5433 -U postgres lattice
    echo "export LATTICE_PG_DSN=postgresql://postgres@localhost:5433/lattice" ;;
  stop) "$PGBIN/pg_ctl" -D "$DIR/pg" stop ;;
  status) "$PGBIN/pg_ctl" -D "$DIR/pg" status ;;
esac
