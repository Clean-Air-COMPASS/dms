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

plugins_dir="/app/qaqc/plugins_local"
seed_dir="/app/qaqc/plugins_local_seed"
if [ -d "$seed_dir" ]; then
  mkdir -p "$plugins_dir"
  if [ -z "$(ls -A "$plugins_dir" 2>/dev/null)" ]; then
    log "Seeding local QC plugins..."
    cp -a "$seed_dir"/. "$plugins_dir"/
  fi
fi

should_run_migrations=true
wait_for_migrations=false
if [ "${1:-}" = "python" ] && [ "${2:-}" = "-m" ] && [ "${3:-}" = "jobs.scheduler" ]; then
  should_run_migrations=false
  wait_for_migrations=true
fi

cd /app

if [ "$should_run_migrations" = "true" ] || [ "$wait_for_migrations" = "true" ]; then
  if ! PG_CONN=$(resolve_pg_conn); then
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
  log "Checking for alembic_version table..."
  if psql "$PG_CONN" -tAc \
    "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='alembic_version';" \
    | grep -q 1; then
    log "Existing schema detected; skipping migrations."
  else
    log "No alembic_version table found; running migrations."
    alembic upgrade head
  fi
fi

if [ "$wait_for_migrations" = "true" ]; then
  log "Waiting for API migrations to complete..."
  until psql "$PG_CONN" -tAc \
    "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='alembic_version';" \
    | grep -q 1; do
    sleep 1
  done
fi

exec "$@"
