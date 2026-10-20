"""Record current CompassAQ results separately from expectation candidates.

The report uses an Alembic-created temporary SQLite database loaded only from
frozen files.  It is diagnostic evidence about the current implementation, not
an oracle and not an input accepted by the promotion command.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import fields, is_dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Iterator


BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REFERENCE_ROOT = Path(__file__).parents[1] / "fixtures" / "reference_data"
DEFAULT_EXPECTED_ROOT = DEFAULT_REFERENCE_ROOT / "expected"


class CurrentObservationError(ValueError):
    pass


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


@contextmanager
def _temporary_environment(name: str, value: str) -> Iterator[None]:
    previous = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


def _jsonable(value: Any, *, field_name: str | None = None) -> Any:
    """Preserve calculation fields while compacting internal identifier lists."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if is_dataclass(value):
        return {
            current_field.name: _jsonable(
                getattr(value, current_field.name), field_name=current_field.name
            )
            for current_field in fields(value)
        }
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): _jsonable(child, field_name=str(key)) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        if field_name and (field_name.endswith("_ids") or field_name == "measurement_ids"):
            return {"omitted_internal_ids": True, "count": len(value)}
        return [_jsonable(child) for child in value]
    return value


def _sqlite_url(database_path: Path) -> str:
    return f"sqlite+pysqlite:///{database_path.resolve().as_posix()}"


def _upgrade_empty_database(database_url: str) -> None:
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    # Several isolated migration unit tests install a minimal ``alembic`` test
    # double in sys.modules while importing a revision.  A full-suite reporter
    # run must not mistake that operation-only double for the installed package.
    cached_alembic = sys.modules.get("alembic")
    if cached_alembic is not None and not hasattr(cached_alembic, "__path__"):
        for module_name in tuple(sys.modules):
            if module_name == "alembic" or module_name.startswith("alembic."):
                sys.modules.pop(module_name, None)
    from alembic.autogenerate import produce_migrations
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.operations.ops import OpContainer
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine

    import models

    configuration = Config(str(BACKEND_ROOT / "alembic.ini"))
    configuration.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    engine = create_engine(database_url)

    def invoke_operation_tree(operations: Operations, operation: Any) -> None:
        if isinstance(operation, OpContainer):
            for child_operation in operation.ops:
                invoke_operation_tree(operations, child_operation)
            return
        operations.invoke(operation)

    with engine.begin() as connection:
        migration_context = MigrationContext.configure(connection)
        migration = produce_migrations(migration_context, models.Base.metadata)
        operations = Operations(migration_context)
        for operation in migration.upgrade_ops.ops:
            invoke_operation_tree(operations, operation)
        migration_context.stamp(
            ScriptDirectory.from_config(configuration),
            "head",
        )
    engine.dispose()


def build_current_observation_report(
    *,
    database_path: Path,
    public_root: Path,
    restricted_root: Path | None,
) -> dict[str, Any]:
    database_url = _sqlite_url(database_path)
    with _temporary_environment("DATABASE_URL", database_url):
        return _build_current_observation_report(
            database_url=database_url,
            public_root=public_root,
            restricted_root=restricted_root,
        )


def _build_current_observation_report(
    *,
    database_url: str,
    public_root: Path,
    restricted_root: Path | None,
) -> dict[str, Any]:
    """Load frozen evidence and serialize service plus API-model observations."""
    _upgrade_empty_database(database_url)
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))

    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool

    import models
    from api.routes.air_quality_index import (
        _collection,
        _us_epa_collection,
        _us_epa_completed_day_history_response,
    )
    from api.routes.measurements import aggregate_measurements
    from reference_data.loader import load_reference_fixture
    from services.air_quality_index.eea_european_service import (
        calculate_eea_european_index_history,
    )
    from services.air_quality_index.us_epa import get_product
    from services.air_quality_index.hourly_pm_completeness import (
        RawHourlyObservation,
        construct_subhourly_pm_hour,
    )
    from services.aqi_engine import calculate_latest_us_epa_aqi
    from services.us_epa_completed_day_service import (
        calculate_us_epa_completed_day_history,
    )
    from services.us_epa_gas_service import (
        calculate_latest_us_epa_carbon_monoxide_aqi,
        calculate_latest_us_epa_nitrogen_dioxide_aqi,
        calculate_latest_us_epa_sulfur_dioxide_aqi,
    )
    from services.us_epa_ozone_service import calculate_latest_us_epa_ozone_aqi

    engine = create_engine(database_url, poolclass=NullPool)
    report: dict[str, Any] = {
        "schema_version": "2i.5-current-observations-1",
        "artifact_kind": "implementation_observations",
        "oracle_status": "not_expected_results",
        "database_creation": (
            "alembic_autogenerated_current_orm_schema_on_empty_temporary_sqlite_"
            "stamped_at_production_head"
        ),
        "provider_calls": 0,
        "credential_reads": 0,
        "purpleair_points_consumed": 0,
        "loaded_fixtures": {},
        "database_retention": {},
        "service_observations": {},
        "api_model_observations": {},
    }
    with Session(engine) as session:
        units = {
            "ug_m3": models.Unit(
                code="ug_m3", symbol="µg/m³", name="Micrograms per cubic meter"
            ),
            "ppm": models.Unit(code="ppm", symbol="ppm", name="Parts per million"),
            "ppb": models.Unit(code="ppb", symbol="ppb", name="Parts per billion"),
        }
        session.add_all(units.values())
        session.flush()
        parameters = {}
        for code, display_name, unit_code in (
            ("pm25", "PM2.5", "ug_m3"),
            ("pm10", "PM10", "ug_m3"),
            ("o3", "O3", "ppm"),
            ("no2", "NO2", "ppm"),
            ("co", "CO", "ppm"),
            ("so2", "SO2", "ppm"),
        ):
            parameter = models.Parameter(
                code=code,
                display_name=display_name,
                default_unit_id=units[unit_code].unit_id,
            )
            session.add(parameter)
            parameters[code] = parameter
        aggregations = {}
        for code, display_name, duration_minutes in (
            ("2m", "2 Minutes", 2),
            ("1h", "1 Hour", 60),
            ("8h", "8 Hour", 480),
            ("24h", "24 Hour", 1440),
        ):
            aggregation = models.AggregationPeriod(
                code=code,
                display_name=display_name,
                duration_minutes=duration_minutes,
                is_rolling=False,
                expected_interval=("00:02:00" if code == "2m" else None),
            )
            session.add(aggregation)
            aggregations[code] = aggregation
        session.flush()

        def add_rule(
            parameter_code: str,
            aggregation_code: str,
            *,
            rounding_method: str = "none",
            rounding_precision: int | None = None,
            truncation_method: str = "none",
            truncation_precision: int | None = None,
        ) -> None:
            session.add(
                models.ParameterAggregationRule(
                    parameter_id=parameters[parameter_code].parameter_id,
                    aggregation_period_id=aggregations[aggregation_code].aggregation_period_id,
                    rounding_method=rounding_method,
                    rounding_precision=rounding_precision,
                    truncation_method=truncation_method,
                    truncation_precision=truncation_precision,
                    active=True,
                )
            )

        add_rule("pm25", "1h", truncation_method="truncate", truncation_precision=1)
        add_rule("pm25", "24h", rounding_method="round", rounding_precision=1)
        add_rule("pm10", "1h", truncation_method="truncate", truncation_precision=0)
        add_rule("pm10", "24h", rounding_method="round", rounding_precision=0)
        add_rule("o3", "1h", rounding_method="round", rounding_precision=3)
        add_rule("o3", "8h", rounding_method="round", rounding_precision=3)
        for parameter_code in ("no2", "co", "so2"):
            add_rule(
                parameter_code,
                "1h",
                rounding_method="round",
                rounding_precision=1,
            )
        for parameter_code in ("pm25", "pm10"):
            session.add(
                models.ParameterAggregationRollup(
                    parameter_id=parameters[parameter_code].parameter_id,
                    from_aggregation_period_id=aggregations["2m"].aggregation_period_id,
                    to_aggregation_period_id=aggregations["1h"].aggregation_period_id,
                )
            )
        session.commit()

        public_summary = load_reference_fixture(session, public_root)
        report["loaded_fixtures"]["openaq"] = _jsonable(public_summary)
        restricted_summary = None
        if restricted_root is not None:
            restricted_summary = load_reference_fixture(session, restricted_root)
            report["loaded_fixtures"]["purpleair"] = _jsonable(restricted_summary)

        sensors = session.execute(
            select(
                models.Sensor.sensor_id,
                models.Sensor.external_sensor_id,
                models.Sensor.hourly_concentration_provenance,
                models.Sensor.hourly_timestamp_semantics,
                models.Sensor.expected_frequency_seconds,
                models.Sensor.measurement_duration_seconds,
                models.Sensor.source_aggregation_duration_seconds,
                models.Sensor.measurement_timestamp_semantics,
                models.Sensor.measurement_metadata_status,
                models.Sensor.measurement_metadata_managed_by,
                models.Parameter.code.label("parameter_code"),
                models.Unit.code.label("unit_code"),
                models.AggregationPeriod.code.label("native_aggregation_period"),
                func.count(models.Measurement.measurement_id).label("measurement_count"),
            )
            .join(models.Parameter, models.Parameter.parameter_id == models.Sensor.parameter_id)
            .outerjoin(models.Unit, models.Unit.unit_id == models.Sensor.unit_id)
            .outerjoin(
                models.AggregationPeriod,
                models.AggregationPeriod.aggregation_period_id
                == models.Sensor.aggregation_period_id,
            )
            .outerjoin(
                models.Measurement, models.Measurement.sensor_id == models.Sensor.sensor_id
            )
            .group_by(models.Sensor.sensor_id)
            .order_by(models.Sensor.sensor_id)
        ).all()
        report["database_retention"]["sensor_streams"] = [
            {key: _jsonable(value) for key, value in row._mapping.items()} for row in sensors
        ]
        measurements = session.scalars(select(models.Measurement)).all()
        required_capture_fields = {
            "provider_observation_ref",
            "source_page",
            "source_result_index",
            "provider_parameter",
        }
        report["database_retention"]["measurements"] = {
            "count": len(measurements),
            "valid_count": sum(measurement.is_valid for measurement in measurements),
            "qc_version_counts": dict(
                sorted(
                    {
                        version: sum(item.qc_version == version for item in measurements)
                        for version in {item.qc_version for item in measurements}
                    }.items(),
                    key=lambda item: str(item[0]),
                )
            ),
            "provider_capture_complete_count": sum(
                required_capture_fields.issubset(
                    (measurement.qc_flags or {})
                    .get("reference_fixture_provider_capture", {})
                    .keys()
                )
                for measurement in measurements
            ),
            "provider_period_count": sum(
                "provider_period"
                in (measurement.qc_flags or {}).get("reference_fixture_provider_capture", {})
                for measurement in measurements
            ),
            "provider_flag_info_count": sum(
                "provider_flag_info"
                in (measurement.qc_flags or {}).get("reference_fixture_provider_capture", {})
                for measurement in measurements
            ),
            "provider_timestamp_count": sum(
                "provider_timestamp"
                in (measurement.qc_flags or {}).get("reference_fixture_provider_capture", {})
                for measurement in measurements
            ),
        }

        evaluation_time = datetime(2026, 8, 12, tzinfo=timezone.utc)

        def device_for_sensor(summary: Any, sensor_ref: str) -> int:
            sensor_id = summary.sensor_ids[sensor_ref]
            return int(session.get(models.Sensor, sensor_id).device_id)

        rio_device_id = device_for_sensor(public_summary, "openaq-sensor-6819305")
        manila_device_id = device_for_sensor(public_summary, "openaq-sensor-13191003")
        bronx_device_id = device_for_sensor(public_summary, "openaq-sensor-1098")
        elizabeth_device_id = device_for_sensor(public_summary, "openaq-sensor-3952")
        new_york_zero_pm10_device_id = device_for_sensor(
            public_summary, "openaq-sensor-1099"
        )
        eea_rio = calculate_eea_european_index_history(
            session,
            start_utc=datetime(2026, 8, 2, 11, tzinfo=timezone.utc),
            end_utc=datetime(2026, 8, 2, 12, tzinfo=timezone.utc),
            device_id=rio_device_id,
            current_time_utc=evaluation_time,
        )
        eea_manila = calculate_eea_european_index_history(
            session,
            start_utc=datetime(2026, 8, 2, 11, tzinfo=timezone.utc),
            end_utc=datetime(2026, 8, 2, 12, tzinfo=timezone.utc),
            device_id=manila_device_id,
            current_time_utc=evaluation_time,
        )
        openaq_services = {
            "eea_rio_2026_08_02T11": eea_rio,
            "eea_openaq_manila_2026_08_02T11": eea_manila,
            "openaq_ny_o3_window_2026_08_02T12": calculate_latest_us_epa_ozone_aqi(
                session,
                product_code="us_epa.o3.latest",
                reference_time_utc=datetime(2026, 8, 2, 12, tzinfo=timezone.utc),
                current_time_utc=evaluation_time,
                device_id=bronx_device_id,
            ),
            "openaq_ny_co_window_2026_08_02T12": calculate_latest_us_epa_carbon_monoxide_aqi(
                session,
                product_code="us_epa.co.latest",
                reference_time_utc=datetime(2026, 8, 2, 12, tzinfo=timezone.utc),
                current_time_utc=evaluation_time,
                device_id=elizabeth_device_id,
            ),
            "openaq_ny_no2_hour_2026_08_02T11": calculate_latest_us_epa_nitrogen_dioxide_aqi(
                session,
                product_code="us_epa.no2.latest",
                reference_time_utc=datetime(2026, 8, 2, 12, tzinfo=timezone.utc),
                current_time_utc=evaluation_time,
                device_id=elizabeth_device_id,
            ),
            "openaq_ny_so2_window_2026_08_02T12": calculate_latest_us_epa_sulfur_dioxide_aqi(
                session,
                product_code="us_epa.so2.latest",
                reference_time_utc=datetime(2026, 8, 2, 12, tzinfo=timezone.utc),
                current_time_utc=evaluation_time,
                device_id=elizabeth_device_id,
            ),
            "openaq_rio_pm10_completed_2026_08_02": calculate_us_epa_completed_day_history(
                session,
                product_code="us_epa.pm10.completed_day",
                start_local_date=date(2026, 8, 2),
                end_local_date=date(2026, 8, 2),
                current_time_utc=evaluation_time,
                device_id=rio_device_id,
            ),
            "openaq_ny_pm10_zero_rows": calculate_latest_us_epa_aqi(
                session,
                product_code="us_epa.pm10.nowcast",
                reference_time_utc=datetime(2026, 8, 2, 12, tzinfo=timezone.utc),
                current_time_utc=evaluation_time,
                device_id=new_york_zero_pm10_device_id,
            ),
            "openaq_outside_adequate_history": calculate_latest_us_epa_aqi(
                session,
                product_code="us_epa.pm25.nowcast",
                reference_time_utc=datetime(2026, 8, 1, tzinfo=timezone.utc),
                current_time_utc=evaluation_time,
                device_id=rio_device_id,
            ),
        }
        openaq_services["openaq_rio_epa_mass_units_unavailable"] = {
            "o3": calculate_latest_us_epa_ozone_aqi(
                session,
                product_code="us_epa.o3.latest",
                reference_time_utc=datetime(2026, 8, 2, 12, tzinfo=timezone.utc),
                current_time_utc=evaluation_time,
                device_id=rio_device_id,
            ),
            "no2": calculate_latest_us_epa_nitrogen_dioxide_aqi(
                session,
                product_code="us_epa.no2.latest",
                reference_time_utc=datetime(2026, 8, 2, 12, tzinfo=timezone.utc),
                current_time_utc=evaluation_time,
                device_id=rio_device_id,
            ),
            "so2": calculate_latest_us_epa_sulfur_dioxide_aqi(
                session,
                product_code="us_epa.so2.latest",
                reference_time_utc=datetime(2026, 8, 2, 12, tzinfo=timezone.utc),
                current_time_utc=evaluation_time,
                device_id=rio_device_id,
            ),
        }
        report["service_observations"].update(
            {case_id: _jsonable(results) for case_id, results in openaq_services.items()}
        )
        report["api_model_observations"]["eea_rio_2026_08_02T11"] = _jsonable(
            _collection(eea_rio)
        )
        report["api_model_observations"]["eea_openaq_manila_2026_08_02T11"] = _jsonable(
            _collection(eea_manila)
        )
        for case_id, product_code in {
            "openaq_ny_o3_window_2026_08_02T12": "us_epa.o3.latest",
            "openaq_ny_co_window_2026_08_02T12": "us_epa.co.latest",
            "openaq_ny_no2_hour_2026_08_02T11": "us_epa.no2.latest",
            "openaq_ny_so2_window_2026_08_02T12": "us_epa.so2.latest",
        }.items():
            report["api_model_observations"][case_id] = _jsonable(
                _us_epa_collection(openaq_services[case_id], product_code)
            )
        completed_product = get_product("us_epa.pm10.completed_day")
        assert completed_product is not None
        report["api_model_observations"]["openaq_rio_pm10_completed_2026_08_02"] = _jsonable(
            _us_epa_completed_day_history_response(
                openaq_services["openaq_rio_pm10_completed_2026_08_02"],
                product=completed_product,
                start_local_date=date(2026, 8, 2),
                end_local_date=date(2026, 8, 2),
                detail="full",
            )
        )

        if restricted_summary is not None:
            ordinary_rows = aggregate_measurements(
                "pm25",
                source_agg="2m",
                target_agg="1h",
                since=datetime(2026, 8, 8, 1, tzinfo=timezone.utc),
                until=datetime(2026, 8, 8, 2, tzinfo=timezone.utc),
                external_api_name="PurpleAir",
                session=session,
            )
            report["service_observations"]["pa_ny_pm25_ordinary_boundary"] = [
                row
                for row in _jsonable(ordinary_rows)
                if row["external_sensor_id"] == "159361:pm2.5_atm"
            ]

            anchored_cases = (
                (
                    "pa_ny_pm_boundary_assignment",
                    datetime(2026, 8, 8, 1, tzinfo=timezone.utc),
                    ("purpleair-159361-pm25", "purpleair-159361-pm10"),
                ),
                (
                    "pa_ny_pm_full",
                    datetime(2026, 8, 10, 5, tzinfo=timezone.utc),
                    ("purpleair-159361-pm25", "purpleair-159361-pm10"),
                ),
                (
                    "pa_ny_pm_duplicate_positions",
                    datetime(2026, 8, 10, 3, tzinfo=timezone.utc),
                    ("purpleair-159361-pm25", "purpleair-159361-pm10"),
                ),
                (
                    "pa_rio_pm_minor_gaps",
                    datetime(2026, 8, 10, 16, tzinfo=timezone.utc),
                    ("purpleair-175407-pm25", "purpleair-175407-pm10"),
                ),
                (
                    "pa_manila_pm_irregular",
                    datetime(2026, 8, 8, 3, tzinfo=timezone.utc),
                    ("purpleair-99177-pm25", "purpleair-99177-pm10"),
                ),
            )
            for case_id, interval_started_at, sensor_refs in anchored_cases:
                interval_ended_at = interval_started_at + timedelta(hours=1)
                case_results = []
                for sensor_ref in sensor_refs:
                    sensor_id = restricted_summary.sensor_ids[sensor_ref]
                    sensor = session.get(models.Sensor, sensor_id)
                    rows = session.scalars(
                        select(models.Measurement)
                        .where(models.Measurement.sensor_id == sensor_id)
                        .where(models.Measurement.observed_at >= interval_started_at)
                        .where(models.Measurement.observed_at <= interval_ended_at)
                        .order_by(
                            models.Measurement.observed_at,
                            models.Measurement.measurement_id,
                        )
                    ).all()
                    observations = [
                        RawHourlyObservation(
                            measurement_id=row.measurement_id,
                            observed_at=row.observed_at,
                            concentration=row.value,
                            is_valid=row.is_valid,
                        )
                        for row in rows
                    ]
                    parameter_code = "pm25" if sensor_ref.endswith("pm25") else "pm10"
                    unit = session.get(models.Unit, sensor.unit_id)
                    result = construct_subhourly_pm_hour(
                        observations,
                        interval_started_at=interval_started_at,
                        parameter_code=parameter_code,
                        input_unit=unit.code,
                        expected_frequency_seconds=sensor.expected_frequency_seconds or 0,
                        measurement_duration_seconds=sensor.measurement_duration_seconds or 0,
                        source_aggregation_duration_seconds=(
                            sensor.source_aggregation_duration_seconds or 0
                        ),
                        timestamp_semantics=sensor.measurement_timestamp_semantics or "",
                    )
                    case_results.append(
                        {
                            "sensor_ref": sensor_ref,
                            "parameter_code": parameter_code,
                            "calculation": _jsonable(result),
                        }
                    )
                report["service_observations"][case_id] = case_results

            for case_id, sensor_ref, boundary in (
                ("pa_ny_pm_nowcast_inputs", "purpleair-159361-pm25", datetime(2026, 8, 10, 12, tzinfo=timezone.utc)),
                ("pa_rio_pm_nowcast_inputs", "purpleair-175407-pm25", datetime(2026, 8, 10, 18, tzinfo=timezone.utc)),
                ("pa_manila_pm_nowcast_inputs", "purpleair-99177-pm25", datetime(2026, 8, 8, 12, tzinfo=timezone.utc)),
            ):
                device_id = device_for_sensor(restricted_summary, sensor_ref)
                service_by_pollutant = {}
                api_by_pollutant = {}
                for pollutant in ("pm25", "pm10"):
                    product_code = f"us_epa.{pollutant}.nowcast"
                    results = calculate_latest_us_epa_aqi(
                        session,
                        product_code=product_code,
                        reference_time_utc=boundary,
                        current_time_utc=evaluation_time,
                        device_id=device_id,
                    )
                    service_by_pollutant[pollutant] = _jsonable(results)
                    api_by_pollutant[pollutant] = _jsonable(
                        _us_epa_collection(results, product_code)
                    )
                report["service_observations"][case_id] = service_by_pollutant
                report["api_model_observations"][case_id] = api_by_pollutant
            ny_device_id = device_for_sensor(restricted_summary, "purpleair-159361-pm25")
            completed_results = calculate_us_epa_completed_day_history(
                session,
                product_code="us_epa.pm25.completed_day",
                start_local_date=date(2026, 8, 9),
                end_local_date=date(2026, 8, 9),
                current_time_utc=evaluation_time,
                device_id=ny_device_id,
            )
            report["service_observations"]["pa_ny_pm25_completed_2026_08_09"] = _jsonable(
                completed_results
            )
            manila_device_id = device_for_sensor(
                restricted_summary, "purpleair-99177-pm25"
            )
            eea_pa_manila = calculate_eea_european_index_history(
                session,
                start_utc=datetime(2026, 8, 8, 3, tzinfo=timezone.utc),
                end_utc=datetime(2026, 8, 8, 4, tzinfo=timezone.utc),
                device_id=manila_device_id,
                current_time_utc=evaluation_time,
            )
            report["service_observations"]["eea_pa_manila_2026_08_08T03"] = _jsonable(
                eea_pa_manila
            )
            report["api_model_observations"]["eea_pa_manila_2026_08_08T03"] = _jsonable(
                _collection(eea_pa_manila)
            )
            zero_row_device_id = device_for_sensor(
                restricted_summary, "purpleair-198733-pm25"
            )
            report["service_observations"]["purpleair_zero_row_sensor_198733"] = _jsonable(
                calculate_latest_us_epa_aqi(
                    session,
                    product_code="us_epa.pm25.nowcast",
                    reference_time_utc=datetime(2026, 8, 10, 12, tzinfo=timezone.utc),
                    current_time_utc=evaluation_time,
                    device_id=zero_row_device_id,
                )
            )
    engine.dispose()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-root", type=Path, default=DEFAULT_REFERENCE_ROOT / "public" / "openaq")
    parser.add_argument("--restricted-root", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-root", type=Path, default=DEFAULT_EXPECTED_ROOT)
    args = parser.parse_args()
    output_path = args.output.resolve()
    if _is_within(output_path, args.expected_root.resolve()):
        raise CurrentObservationError(
            "Current CompassAQ observations cannot be written inside expected results"
        )
    if args.restricted_root is not None:
        restricted_root = args.restricted_root.resolve()
    else:
        if str(BACKEND_ROOT) not in sys.path:
            sys.path.insert(0, str(BACKEND_ROOT))
        from reference_data.restricted import resolve_restricted_data_root

        restricted_root = resolve_restricted_data_root(
            checked_in_fallback=DEFAULT_REFERENCE_ROOT / "restricted" / "purpleair"
        )
    with tempfile.TemporaryDirectory(prefix="compassaq-2i5-") as temporary_directory:
        report = build_current_observation_report(
            database_path=Path(temporary_directory) / "observations.sqlite3",
            public_root=args.public_root.resolve(),
            restricted_root=restricted_root,
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
