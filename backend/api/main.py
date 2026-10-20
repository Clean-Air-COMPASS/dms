import logging
import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
import qaqc.plugins
from api.auth_deps import require_scopes
from api.routes.admin.devices import router as admin_devices_router
from api.routes.admin.airgradient_devices import router as admin_airgradient_devices_router
from api.routes.admin.diagnostics import router as admin_diag_router
from api.routes.admin.email import router as admin_email_router
from api.routes.admin.events import router as admin_events_router
from api.routes.admin.external_apis import router as admin_external_apis_router
from api.routes.admin.imports import router as admin_imports_router
from api.routes.admin.jobs import router as admin_jobs_router
from api.routes.admin.plugins import router as admin_plugins_router
from api.routes.admin.qc_policies import router as admin_qc_policies_router
from api.routes.admin.qc_rules import router as admin_qc_router
from api.routes.admin.system_preferences import router as admin_system_preferences_router
from api.routes.admin.users import router as admin_users_router
from api.routes.air_quality_index import router as air_quality_index_router
from api.routes.auth import router as auth_router
from api.routes.account import router as account_router
from api.routes.password_reset import router as password_reset_router
from api.routes.passkeys import router as passkeys_router
from api.routes.general import router as general_router
from api.routes.geocode import router as geocode_router
from api.routes.health import router as health_router
from api.routes.version import router as version_router
from build_identity import APPLICATION_VERSION
from api.routes.measurements import router as measurements_router
from api.routes.programmatic_imports import router as programmatic_imports_router
from api.routes.sensors import router as sensors_router
from api.routes.setup import router as setup_router
from db import SessionLocal
from qaqc import discovery, registry
from reference_data.default_devices import initialize_default_reference_devices
from services.external_sources import ensure_builtin_external_apis


logger = logging.getLogger(__name__)

app = FastAPI(title="CompassAQ API", version=APPLICATION_VERSION)


cors_origins_raw = os.environ.get("CORS_ALLOW_ORIGINS", "").strip()
if cors_origins_raw:
    cors_origins = [origin.strip() for origin in cors_origins_raw.split(",") if origin.strip()]
    if "*" in cors_origins:
        raise ValueError("CORS_ALLOW_ORIGINS must not include '*' when allow_credentials is enabled.")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
app.include_router(general_router)
app.include_router(health_router)
app.include_router(version_router)
app.include_router(auth_router)
app.include_router(account_router)
app.include_router(password_reset_router)
app.include_router(passkeys_router)
app.include_router(air_quality_index_router)
app.include_router(measurements_router)
app.include_router(sensors_router)
admin_scope = [Depends(require_scopes(["users:write"]))]
app.include_router(admin_jobs_router, dependencies=admin_scope)
app.include_router(admin_devices_router, dependencies=admin_scope)
app.include_router(admin_airgradient_devices_router, dependencies=admin_scope)
app.include_router(admin_external_apis_router, dependencies=admin_scope)
app.include_router(admin_diag_router, dependencies=admin_scope)
app.include_router(admin_email_router, dependencies=admin_scope)
app.include_router(admin_qc_policies_router, dependencies=admin_scope)
app.include_router(admin_qc_router, dependencies=admin_scope)
app.include_router(admin_plugins_router, dependencies=admin_scope)
app.include_router(admin_imports_router, dependencies=admin_scope)
app.include_router(admin_events_router, dependencies=admin_scope)
app.include_router(admin_system_preferences_router, dependencies=admin_scope)
app.include_router(admin_users_router, dependencies=admin_scope)
app.include_router(programmatic_imports_router)
app.include_router(geocode_router)
app.include_router(setup_router)


@app.on_event("startup")
async def _load_plugins_on_startup():
    try:
        report = discovery.load_plugins()
        loaded = ", ".join(sorted(list(registry.all_plugins().keys())))
        logger.info(
            "QA/QC discovery loaded built_in=%s entry_points=%s rejected=%s failed=%s registered=%s",
            len(report.get("built_in", [])),
            len(report.get("entry_points", [])),
            len(report.get("rejected", [])),
            len(report.get("failed", [])),
            loaded,
        )
    except Exception as exc:
        logger.exception("QA/QC plugin discovery failed: %s", exc)

    try:
        with SessionLocal() as s:
            ensure_builtin_external_apis(s)
            initialize_default_reference_devices(s)
            s.commit()
    except Exception as exc:
        logger.exception("Failed to seed external API rows: %s", exc)


if __name__ == "__main__":
    try:
        import uvicorn
    except Exception:
        logger.exception("uvicorn is not installed; run with `uvicorn api.main:app` instead")
    else:
        bind_host = os.environ.get("BIND_HOST") or os.environ.get("API_HOST") or os.environ.get("HOST") or "0.0.0.0"
        bind_port = int(os.environ.get("BIND_PORT") or os.environ.get("API_PORT") or 8000)
        logger.info("Starting uvicorn on %s:%s", bind_host, bind_port)
        uvicorn.run(app, host=bind_host, port=bind_port, log_level="info")
