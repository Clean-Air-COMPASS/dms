import os
from urllib.parse import quote_plus


def resolve_database_url() -> str:
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return db_url

    required = [
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
    ]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        missing_str = ", ".join(missing)
        raise RuntimeError(
            "Database configuration is incomplete. Missing: "
            f"{missing_str}. Set DATABASE_URL or POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB "
            "(optional: POSTGRES_HOST, POSTGRES_PORT)."
        )

    user = os.getenv("POSTGRES_USER", "")
    password = os.getenv("POSTGRES_PASSWORD", "")
    db_name = os.getenv("POSTGRES_DB", "")

                                          
                                                                                   
                                                                                             
    in_docker = os.path.exists("/.dockerenv")
    host_raw = (os.getenv("POSTGRES_HOST") or "").strip()
    port_env = (os.getenv("POSTGRES_PORT") or "").strip()

    if host_raw:
        host = host_raw
    elif in_docker:
        host = "db"
    else:
        raise RuntimeError(
            "Database configuration is incomplete. Missing: POSTGRES_HOST. "
            "Set DATABASE_URL or POSTGRES_HOST (optional: POSTGRES_PORT)."
        )

    if host == "db" and in_docker:
        port = "5432"
    else:
        port = port_env or "5432"

    return (
        "postgresql+psycopg://"
        f"{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{db_name}"
    )
