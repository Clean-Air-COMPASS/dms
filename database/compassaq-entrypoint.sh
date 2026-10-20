#!/usr/bin/env bash
set -Eeuo pipefail

# Keep the official PostgreSQL initialization and upgrade behavior, but make
# POSTGRES_PASSWORD effective for an existing Compose volume as well. The
# official image uses POSTGRES_PASSWORD only while creating a new cluster;
# without this synchronization, removing or changing an old .env value leaves
# the application unable to connect even though pg_isready reports healthy.
official_entrypoint=/usr/local/bin/docker-entrypoint.sh
readonly compassaq_database_role="compassaq"

if [[ "${1:-}" != "postgres" ]]; then
    exec "$official_entrypoint" "$@"
fi

database_user="${POSTGRES_USER:-$compassaq_database_role}"
database_name="${POSTGRES_DB:-$database_user}"
database_password="${POSTGRES_PASSWORD:-}"
if [[ -z "$database_password" && -n "${POSTGRES_PASSWORD_FILE:-}" ]]; then
    database_password="$(< "$POSTGRES_PASSWORD_FILE")"
fi

"$official_entrypoint" "$@" &
postgres_entrypoint_pid=$!

forward_shutdown() {
    kill -TERM "$postgres_entrypoint_pid" 2>/dev/null || true
}

trap forward_shutdown TERM INT QUIT

if [[ -n "$database_password" && "$database_user" == "$compassaq_database_role" ]]; then
    # The official image configures the local socket for trusted initialization
    # access. Use that local superuser path to update the configured role before
    # the Compose healthcheck permits API or scheduler startup.
    while ! gosu postgres psql \
        --no-password \
        --no-psqlrc \
        --username "$compassaq_database_role" \
        --dbname "$database_name" \
        --tuples-only \
        --command 'SELECT 1' >/dev/null 2>&1; do
        if ! kill -0 "$postgres_entrypoint_pid" 2>/dev/null; then
            if wait "$postgres_entrypoint_pid"; then
                exit 1
            else
                exit $?
            fi
        fi
        sleep 1
    done

    database_owner="$(gosu postgres psql \
        --no-password \
        --no-psqlrc \
        --username "$compassaq_database_role" \
        --dbname "$database_name" \
        --tuples-only \
        --no-align \
        --command 'SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database();')"
    if [[ "$database_owner" != "$compassaq_database_role" ]]; then
        printf 'Refusing to synchronize credentials: database %s is owned by role %s, not the CompassAQ role %s.\n' \
            "$database_name" "${database_owner:-<unknown>}" "$compassaq_database_role" >&2
        kill -TERM "$postgres_entrypoint_pid" 2>/dev/null || true
        wait "$postgres_entrypoint_pid" || true
        exit 1
    fi

    printf 'Synchronizing PostgreSQL credentials for role %s...\n' "$database_user"
    if ! gosu postgres psql \
        --no-password \
        --no-psqlrc \
        --username "$compassaq_database_role" \
        --dbname "$database_name" \
        --set=db_password="$database_password" \
        --set=ON_ERROR_STOP=1 \
        <<'SQL'
ALTER ROLE compassaq PASSWORD :'db_password';
SQL
    then
        printf 'Could not synchronize the PostgreSQL password for role %s; refusing to continue.\n' "$database_user" >&2
        kill -TERM "$postgres_entrypoint_pid" 2>/dev/null || true
        wait "$postgres_entrypoint_pid" || true
        exit 1
    fi
    printf 'PostgreSQL credentials synchronized.\n'
elif [[ -n "$database_password" ]]; then
    printf 'Skipping credential synchronization for configured role %s; only the CompassAQ role %s is managed by this image.\n' \
        "$database_user" "$compassaq_database_role"
fi

if wait "$postgres_entrypoint_pid"; then
    exit 0
else
    exit $?
fi
