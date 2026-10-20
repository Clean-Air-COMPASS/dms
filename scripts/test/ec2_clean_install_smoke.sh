#!/usr/bin/env bash
set -euo pipefail

# Destructive clean-install smoke test for the dedicated disposable EC2 test host.
#
# The caller must provide a freshly cloned CompassAQ checkout through SOURCE_DIR.
# This script deliberately removes prior CompassAQ test containers and volumes,
# then verifies a clean Docker install can start and survive a container restart.

SOURCE_DIR="${SOURCE_DIR:-}"
TEST_DIR="${TEST_DIR:-/opt/compassaq-clean-install}"
BUILDX_VERSION="${BUILDX_VERSION:-0.36.1}"
BUILDX_SHA256="${BUILDX_SHA256:-48af8a397ebd60178778bf63611dbcebe5f5e7a9be90eb9147b24b9587455778}"

if [[ -z "$SOURCE_DIR" || ! -f "$SOURCE_DIR/docker-compose.yml" ]]; then
  echo "SOURCE_DIR must point to a fresh CompassAQ checkout." >&2
  exit 2
fi

failure_diagnostics() {
  local rc=$?
  echo "=== FAILURE DIAGNOSTICS ==="
  if [[ -f "$TEST_DIR/docker-compose.yml" ]]; then
    cd "$TEST_DIR" || true
    docker compose ps || true
    docker compose logs --tail=120 || true
  fi
  exit "$rc"
}
trap failure_diagnostics ERR

ensure_buildx() {
  echo "=== ensure compatible docker buildx ==="
  if docker buildx version 2>/dev/null | grep -q "v${BUILDX_VERSION}"; then
    docker buildx version
    return
  fi

  local download=/tmp/docker-buildx
  mkdir -p /usr/local/libexec/docker/cli-plugins
  curl -fsSL \
    "https://github.com/docker/buildx/releases/download/v${BUILDX_VERSION}/buildx-v${BUILDX_VERSION}.linux-amd64" \
    -o "$download"
  echo "${BUILDX_SHA256}  ${download}" | sha256sum -c -
  install -m 0755 "$download" /usr/local/libexec/docker/cli-plugins/docker-buildx
  rm -f "$download"
  docker buildx version
}

wait_for_setup_status() {
  local output_file=$1
  local attempts=$2

  rm -f "$output_file"
  for _ in $(seq 1 "$attempts"); do
    if curl -fsS http://127.0.0.1/api/setup/status >"$output_file" 2>/dev/null; then
      return 0
    fi
    sleep 5
  done
  return 1
}

ensure_buildx

echo "=== clean previous smoke-test state ==="
if [[ -f "$TEST_DIR/docker-compose.yml" ]]; then
  (
    cd "$TEST_DIR"
    docker compose down -v --remove-orphans || true
  )
fi
cd /
docker rm -f aq_db aq_api aq_scheduler aq_frontend aq_adminer 2>/dev/null || true
rm -rf "$TEST_DIR"
mkdir -p "$(dirname "$TEST_DIR")"
mv "$SOURCE_DIR" "$TEST_DIR"
chown -R root:root "$TEST_DIR"
cd "$TEST_DIR"

echo "=== verify clean configuration ==="
test ! -e .env
echo "commit=$(git rev-parse HEAD)"
docker compose config >/tmp/compassaq-compose-config.txt
echo "docker-compose-config=valid"

echo "=== build and start ==="
docker compose up -d --build
wait_for_setup_status /tmp/compassaq-setup-status.json 90
test -s /tmp/compassaq-setup-status.json
cat /tmp/compassaq-setup-status.json
grep -q '"is_setup_required":true' /tmp/compassaq-setup-status.json
grep -q '"has_users":false' /tmp/compassaq-setup-status.json
grep -q '"default_language_code":"en"' /tmp/compassaq-setup-status.json

echo "=== complete first-run setup ==="
curl -fsS -X POST http://127.0.0.1/api/setup/admin \
  -H 'Content-Type: application/json' \
  --data '{"email":"setup-smoke@example.com","password":"CompassAQSmokeSetup123!","confirm_password":"CompassAQSmokeSetup123!"}' \
  >/tmp/compassaq-setup-admin.json
curl -fsS -X POST http://127.0.0.1/api/setup/complete \
  -H 'Content-Type: application/json' \
  --data '{"default_language_code":"en","system_timezone":"UTC"}' \
  >/tmp/compassaq-setup-complete.json
wait_for_setup_status /tmp/compassaq-setup-status-complete.json 30
cat /tmp/compassaq-setup-status-complete.json
grep -q '"is_setup_required":false' /tmp/compassaq-setup-status-complete.json
grep -q '"has_users":true' /tmp/compassaq-setup-status-complete.json
grep -q '"default_language_code":"en"' /tmp/compassaq-setup-status-complete.json

echo "=== verify published web and proxied API entry point ==="
curl -fsS http://127.0.0.1/ >/tmp/compassaq-index.html
test -s /tmp/compassaq-index.html
grep -qi '<!doctype html' /tmp/compassaq-index.html
curl -fsS http://127.0.0.1/api/setup/status >/tmp/compassaq-proxied-api.json
grep -q is_setup_required /tmp/compassaq-proxied-api.json
PUBLISHED_FRONTEND=$(docker compose port frontend 80)
printf 'frontend-published=%s\n' "$PUBLISHED_FRONTEND"
echo "$PUBLISHED_FRONTEND" | grep -Eq '^0\.0\.0\.0:[0-9]+$'
echo "public-entry-point=verified"

echo "=== generate and capture runtime-secret fingerprints ==="
docker compose exec -T api python -c \
  "from services.runtime_secrets import get_or_create_jwt_secret,get_or_create_encryption_key; get_or_create_jwt_secret(); get_or_create_encryption_key()"
BEFORE=$(docker compose exec -T api sh -lc \
  "sha256sum /var/lib/compassaq/jwt_secret /var/lib/compassaq/encryption_key")
printf '%s\n' "$BEFORE"

echo "=== restart containers without recreating them ==="
docker compose restart api scheduler frontend
wait_for_setup_status /tmp/compassaq-setup-status-after-restart.json 60
grep -q '"is_setup_required":false' /tmp/compassaq-setup-status-after-restart.json
grep -q '"has_users":true' /tmp/compassaq-setup-status-after-restart.json
grep -q '"default_language_code":"en"' /tmp/compassaq-setup-status-after-restart.json

echo "=== recreate containers without deleting volumes ==="
docker compose down --remove-orphans
docker compose up -d
wait_for_setup_status /tmp/compassaq-setup-status-after-recreate.json 60
test -s /tmp/compassaq-setup-status-after-recreate.json
grep -q '"is_setup_required":false' /tmp/compassaq-setup-status-after-recreate.json
grep -q '"has_users":true' /tmp/compassaq-setup-status-after-recreate.json
grep -q '"default_language_code":"en"' /tmp/compassaq-setup-status-after-recreate.json
AFTER=$(docker compose exec -T api sh -lc \
  "sha256sum /var/lib/compassaq/jwt_secret /var/lib/compassaq/encryption_key")
test "$BEFORE" = "$AFTER"
echo "generated-secrets=persisted"

echo "=== final service state ==="
docker compose ps
echo "CLEAN_INSTALL_SMOKE_TEST=PASS"
trap - ERR
