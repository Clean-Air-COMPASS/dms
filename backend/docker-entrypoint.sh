#!/bin/sh
set -eu

log() {
  printf '%s\n' "$*"
}

resolve_pg_conn() {
  python - <<'PY'
from __future__ import annotations

import importlib.util

spec = importlib.util.spec_from_file_location("db_config", "db/config.py")
if spec is None or spec.loader is None:
    raise SystemExit(1)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
resolve_database_url = getattr(mod, "resolve_database_url", None)
if resolve_database_url is None:
    raise SystemExit(1)

try:
    url = resolve_database_url()
except Exception:
    raise SystemExit(1)

if url.startswith("sqlite"):
    raise SystemExit(2)

if url.startswith("postgresql+psycopg://"):
    url = "postgresql://" + url.split("://", 1)[1]

if not (url.startswith("postgresql://") or url.startswith("postgres://")):
    raise SystemExit(2)

print(url)
PY
}

should_run_migrations=true
wait_for_migrations=false
if [ "${1:-}" = "python" ] && [ "${2:-}" = "-m" ] && [ "${3:-}" = "jobs.scheduler" ]; then
  should_run_migrations=false
  wait_for_migrations=true
fi

cd /app

if [ "$should_run_migrations" = "true" ] || [ "$wait_for_migrations" = "true" ]; then
  if PG_CONN=$(resolve_pg_conn); then
    :
  else
    exit_code=$?
    if [ "$exit_code" -eq 1 ]; then
      log "Database configuration is incomplete. Set DATABASE_URL or POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB (optional: POSTGRES_HOST/POSTGRES_PORT)."
    else
      log "DATABASE_URL must be a Postgres URL to run migrations."
    fi
    exit 1
  fi

  log "Waiting for Postgres to accept connections..."
  until pg_isready --dbname "$PG_CONN" >/dev/null 2>&1; do
    sleep 1
  done
fi

if [ "$should_run_migrations" = "true" ]; then
  log "Applying database migrations..."
  alembic upgrade head
fi

if [ "$wait_for_migrations" = "true" ]; then
  migration_head=$(alembic heads | awk 'NR == 1 {print $1}')
  if [ -z "$migration_head" ]; then
    log "Could not resolve the Alembic migration head."
    exit 1
  fi
  log "Waiting for API migrations to reach ${migration_head}..."
  until psql "$PG_CONN" -tAc \
    "SELECT to_regclass('public.alembic_version') IS NOT NULL;" \
    | grep -q t \
    && psql "$PG_CONN" -tAc \
    "SELECT EXISTS (SELECT 1 FROM alembic_version WHERE version_num='${migration_head}');" \
    | grep -q t; do
    sleep 1
  done
fi

exec "$@"
