import os
import sys
import uuid
from pathlib import Path

import pytest

# Set safety-sensitive environment state before importing any application
# modules. Provider subprocesses inherit these values as an independent guard.
os.environ["COMPASSAQ_ENV"] = "test"
os.environ["DISABLE_PAID_API_REQUESTS"] = "true"

backend_root = Path(__file__).resolve().parents[1]
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

                                                                               
default_sqlite_path = backend_root / "tests" / "testdata.sqlite3"
default_sqlite_url = f"sqlite+pysqlite:///{default_sqlite_path}"
# The ordinary suite must never bind to a developer or deployment database.
# PostgreSQL-specific tests use COMPASSAQ_POSTGRES_TEST_URL and create their own
# temporary database through postgresql_test_support.py.
default_sqlite_path.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = default_sqlite_url
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

from sqlalchemy import select              

import db              
import models              


@pytest.fixture(scope="session", autouse=True)
def load_deployment_installed_qc_plugins():
    """Mirror backend startup discovery for direct ingest and API tests."""
    from qaqc import discovery

    discovery.load_plugins()


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch):
    """Fail tests immediately if application code attempts external HTTP."""
    import ipaddress
    import socket
    import httpx
    import requests

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def provider_name(target) -> str:
        normalized = str(target).lower()
        if "purpleair" in normalized:
            return "PurpleAir"
        if "openaq" in normalized:
            return "OpenAQ"
        if "airgradient" in normalized:
            return "AirGradient"
        return "arbitrary external"

    def is_loopback_address(address) -> bool:
        host = address[0] if isinstance(address, tuple) and address else address
        if host in {"localhost", "localhost.localdomain"}:
            return True
        try:
            return ipaddress.ip_address(str(host)).is_loopback
        except ValueError:
            return False

    def guarded_connect(sock, address):
        if not is_loopback_address(address):
            raise RuntimeError(
                f"{provider_name(address)} socket blocked in offline tests: {address!r}"
            )
        return original_connect(sock, address)

    def guarded_connect_ex(sock, address):
        if not is_loopback_address(address):
            raise RuntimeError(
                f"{provider_name(address)} socket blocked in offline tests: {address!r}"
            )
        return original_connect_ex(sock, address)

    def blocked_requests(*args, **kwargs):
        target = kwargs.get("url") or (args[1] if len(args) > 1 else args[0] if args else "")
        raise RuntimeError(
            "Requests external HTTP is blocked in offline tests "
            f"(provider seam: {provider_name(target)})"
        )

    def blocked_httpx_sync(*args, **kwargs):
        request = args[1] if len(args) > 1 else kwargs.get("request")
        target = getattr(request, "url", request)
        raise RuntimeError(
            "HTTPX external HTTP is blocked in offline tests "
            f"(provider seam: {provider_name(target)})"
        )

    async def blocked_httpx_async(*args, **kwargs):
        request = args[1] if len(args) > 1 else kwargs.get("request")
        target = getattr(request, "url", request)
        raise RuntimeError(
            "HTTPX external HTTP is blocked in offline tests "
            f"(provider seam: {provider_name(target)})"
        )

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(requests.sessions.Session, "request", blocked_requests)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked_httpx_sync)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", blocked_httpx_async)

                                                                                            
if db.DATABASE_URL.startswith("sqlite"):
                                                
    models.Base.metadata.create_all(bind=db.engine)

    with db.SessionLocal() as session:
        from models import (
            AggregationPeriod,
            Parameter,
            ParameterAggregationRule,
            ParameterSupportedUnit,
            Unit,
        )

        existing_units = {row.code: row for row in session.scalars(select(Unit)).all()}
        if "ug_m3" not in existing_units:
            ug_unit = Unit(code="ug_m3", symbol="µg/m³", name="Micrograms per cubic meter")
            session.add(ug_unit)
            session.flush()
            existing_units["ug_m3"] = ug_unit
        if "ppm" not in existing_units:
            ppm_unit = Unit(code="ppm", symbol="ppm", name="Parts per million")
            session.add(ppm_unit)
            session.flush()
            existing_units["ppm"] = ppm_unit
        if "ppb" not in existing_units:
            ppb_unit = Unit(code="ppb", symbol="ppb", name="Parts per billion")
            session.add(ppb_unit)
            session.flush()
            existing_units["ppb"] = ppb_unit
        for unit_code, symbol, name in (
            ("mg_m3", "mg/m³", "Milligrams per cubic meter"),
            ("celsius", "°C", "Degrees Celsius"),
            ("kelvin", "K", "Kelvin"),
            ("percent", "%", "Percent"),
            ("index", "index", "Unitless index"),
        ):
            if unit_code not in existing_units:
                unit = Unit(code=unit_code, symbol=symbol, name=name)
                session.add(unit)
                session.flush()
                existing_units[unit_code] = unit

        existing_params = {row.code: row for row in session.scalars(select(Parameter)).all()}
        def _ensure_param(code: str, display: str, unit_code: str) -> Parameter:
            if code in existing_params:
                return existing_params[code]
            param = Parameter(code=code, display_name=display, default_unit_id=existing_units[unit_code].unit_id)
            session.add(param)
            session.flush()
            existing_params[code] = param
            return param

        _ensure_param("pm25", "PM2.5", "ug_m3")
        _ensure_param("pm10", "PM10", "ug_m3")
        _ensure_param("o3", "O3", "ppm")
        _ensure_param("no2", "NO2", "ppm")
        _ensure_param("co", "CO", "ppm")
        _ensure_param("so2", "SO2", "ppm")
        _ensure_param("no", "NO", "ppb")

        existing_supported_units = {
            (row.parameter_id, row.unit_id)
            for row in session.scalars(select(ParameterSupportedUnit)).all()
        }
        supported_unit_codes = {
            "pm25": ("ug_m3",),
            "pm10": ("ug_m3",),
            "o3": ("ppm", "ppb", "ug_m3"),
            "no2": ("ppm", "ppb", "ug_m3"),
            "so2": ("ppm", "ppb", "ug_m3"),
            "co": ("ppm", "ppb", "ug_m3", "mg_m3"),
            "no": ("ppb",),
        }
        for parameter_code, unit_codes in supported_unit_codes.items():
            parameter = existing_params[parameter_code]
            for unit_code in unit_codes:
                key = (parameter.parameter_id, existing_units[unit_code].unit_id)
                if key not in existing_supported_units:
                    session.add(
                        ParameterSupportedUnit(
                            parameter_id=key[0],
                            unit_id=key[1],
                        )
                    )
                    existing_supported_units.add(key)

        existing_aggs = {row.code: row for row in session.scalars(select(AggregationPeriod)).all()}
        legacy_aqi_period = existing_aggs.pop("aqi", None)
        if legacy_aqi_period is not None:
            referenced_sensor = session.scalar(
                select(models.Sensor).where(
                    models.Sensor.aggregation_period_id
                    == legacy_aqi_period.aggregation_period_id
                )
            )
            if referenced_sensor is not None:
                raise RuntimeError(
                    "The test database contains a sensor using the removed "
                    "legacy AQI aggregation period."
                )
            legacy_rules = session.scalars(
                select(ParameterAggregationRule).where(
                    ParameterAggregationRule.aggregation_period_id
                    == legacy_aqi_period.aggregation_period_id
                )
            ).all()
            for legacy_rule in legacy_rules:
                session.delete(legacy_rule)
            session.delete(legacy_aqi_period)
            session.flush()

        def _ensure_agg(code: str, display: str, **fields) -> AggregationPeriod:
            if code in existing_aggs:
                agg = existing_aggs[code]
                for field, value in fields.items():
                    setattr(agg, field, value)
                return agg
            agg = AggregationPeriod(code=code, display_name=display, **fields)
            session.add(agg)
            session.flush()
            existing_aggs[code] = agg
            return agg

        _ensure_agg("1h", "1 Hour")
        _ensure_agg(
            "2m",
            "2 Minutes",
            duration_minutes=2,
            is_rolling=False,
            expected_interval="00:02:00",
        )
        _ensure_agg("8h", "8 Hour")
        _ensure_agg("24h", "24 Hour")

        existing_rules = {
            (row.parameter.code, row.aggregation_period.code): row
            for row in session.scalars(select(ParameterAggregationRule)).all()
        }

        def _ensure_rule(param_code: str, agg_code: str, **kwargs) -> None:
            key = (param_code, agg_code)
            if key in existing_rules:
                rule = existing_rules[key]
                for field, value in kwargs.items():
                    setattr(rule, field, value)
                return
            rule = ParameterAggregationRule(
                parameter_id=existing_params[param_code].parameter_id,
                aggregation_period_id=existing_aggs[agg_code].aggregation_period_id,
                **kwargs,
            )
            session.add(rule)
            existing_rules[key] = rule

        _ensure_rule("pm25", "1h", truncation_method="truncate", truncation_precision=1)
        _ensure_rule("pm25", "24h", rounding_method="round", rounding_precision=1)
        _ensure_rule("pm10", "1h", truncation_method="truncate", truncation_precision=0)
        _ensure_rule("pm10", "24h", rounding_method="round", rounding_precision=0)
        _ensure_rule("o3", "1h", rounding_method="round", rounding_precision=3)
        _ensure_rule("o3", "8h", rounding_method="round", rounding_precision=3)
        for code in ("no2", "co", "so2"):
            _ensure_rule(code, "1h", rounding_method="round", rounding_precision=1)
        _ensure_rule("no", "1h", rounding_method="round", rounding_precision=1)
        session.commit()
@pytest.fixture()
def admin_auth_headers():
    from services import auth
    from db import SessionLocal
    import models

    settings = auth.get_auth_settings()
    with SessionLocal() as session:
        user = models.User(
            user_id=uuid.uuid4(),
            org_id=uuid.uuid4(),
            email=f"admin-{uuid.uuid4()}@example.com",
            password_hash=auth.hash_password("strong-password-123"),
            is_active=True,
        )
        session.add(user)
        session.commit()

        token, _ = auth.create_access_token(
            settings=settings,
            user_id=user.user_id,
            org_id=user.org_id,
            roles=["admin"],
            scopes=auth.scopes_from_roles(["admin"]),
        )
    return {"Authorization": f"Bearer {token}"}
