from __future__ import annotations

"""Record current Philippine AQI results outside the expectation tree.

The reporter reuses the Phase 2I.5 temporary-database and frozen-fixture loader
architecture. Production services and API serialization are observation sources
only; their output is never written into an expectation bundle.
"""

import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

try:
    from .current_observations import (
        BACKEND_ROOT,
        DEFAULT_EXPECTED_ROOT,
        DEFAULT_REFERENCE_ROOT,
        CurrentObservationError,
        _is_within,
        _temporary_environment,
        _upgrade_empty_database,
    )
except ImportError:
    from current_observations import (
        BACKEND_ROOT,
        DEFAULT_EXPECTED_ROOT,
        DEFAULT_REFERENCE_ROOT,
        CurrentObservationError,
        _is_within,
        _temporary_environment,
        _upgrade_empty_database,
    )


REAL_CASES = (
    {
        "case_id": "openaq_pm25_completed_2026_08_02",
        "dataset": "openaq",
        "provider": "OpenAQ",
        "sensor_ref": "openaq-sensor-13191003",
        "parameter_code": "pm25",
        "product_code": "philippines_denr.pm25.completed_day",
        "represented_local_date": "2026-08-02",
        "utc_window_started_at": "2026-08-01T16:00:00Z",
        "utc_window_ended_at": "2026-08-02T16:00:00Z",
    },
    {
        "case_id": "purpleair_pm25_completed_2026_08_09",
        "dataset": "purpleair",
        "provider": "PurpleAir",
        "sensor_ref": "purpleair-99177-pm25",
        "parameter_code": "pm25",
        "product_code": "philippines_denr.pm25.completed_day",
        "represented_local_date": "2026-08-09",
        "utc_window_started_at": "2026-08-08T16:00:00Z",
        "utc_window_ended_at": "2026-08-09T16:00:00Z",
    },
    {
        "case_id": "purpleair_pm10_completed_2026_08_09",
        "dataset": "purpleair",
        "provider": "PurpleAir",
        "sensor_ref": "purpleair-99177-pm10",
        "parameter_code": "pm10",
        "product_code": "philippines_denr.pm10.completed_day",
        "represented_local_date": "2026-08-09",
        "utc_window_started_at": "2026-08-08T16:00:00Z",
        "utc_window_ended_at": "2026-08-09T16:00:00Z",
    },
)


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _measurement_id_sha256(measurement_ids: tuple[int, ...]) -> str:
    serialized = ",".join(str(value) for value in measurement_ids).encode("ascii")
    return sha256(serialized).hexdigest()


def _seed_reference_metadata(session: Any) -> None:
    import models

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
            expected_interval="00:02:00" if code == "2m" else None,
        )
        session.add(aggregation)
        aggregations[code] = aggregation
    session.flush()

    for parameter_code, aggregation_code in (
        ("pm25", "1h"),
        ("pm25", "24h"),
        ("pm10", "1h"),
        ("pm10", "24h"),
        ("o3", "1h"),
        ("o3", "8h"),
        ("no2", "1h"),
        ("co", "1h"),
        ("so2", "1h"),
    ):
        session.add(
            models.ParameterAggregationRule(
                parameter_id=parameters[parameter_code].parameter_id,
                aggregation_period_id=(
                    aggregations[aggregation_code].aggregation_period_id
                ),
                rounding_method="none",
                truncation_method="none",
                active=True,
            )
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


def _case_observation(
    session: Any,
    fixture_summaries: dict[str, Any],
    case: dict[str, str],
) -> dict[str, Any]:
    import models
    from api.routes.air_quality_index import _philippine_collection
    from services.air_quality_index.philippines_denr_service import (
        calculate_philippine_aqi_history,
    )

    summary = fixture_summaries[case["dataset"]]
    sensor_id = summary.sensor_ids[case["sensor_ref"]]
    sensor = session.get(models.Sensor, sensor_id)
    device = session.get(models.Device, sensor.device_id)
    unit = session.get(models.Unit, sensor.unit_id)
    start = _timestamp(case["utc_window_started_at"])
    end = _timestamp(case["utc_window_ended_at"])
    results = calculate_philippine_aqi_history(
        session,
        product_code=case["product_code"],
        start_utc=start,
        end_utc=end + timedelta(microseconds=1),
        device_id=device.device_id,
        limit=10,
    )
    selected_result = next(
        result
        for result in results
        if result.represented_local_date.isoformat()
        == case["represented_local_date"]
    )
    selected_evaluation = next(
        evaluation
        for evaluation in selected_result.candidate_sensor_evaluations
        if evaluation.sensor.sensor_id == selected_result.selected_sensor_id
    )
    calculation = selected_result.calculation
    duplicate_ids = tuple(
        measurement_id
        for hour in selected_evaluation.hourly_inputs
        for measurement_id in hour.duplicate_measurement_ids
    )
    rejected_ids = tuple(
        measurement_id
        for hour in selected_evaluation.hourly_inputs
        for measurement_id in hour.rejected_measurement_ids
    )
    off_frequency_ids = tuple(
        measurement_id
        for hour in selected_evaluation.hourly_inputs
        for measurement_id in hour.off_frequency_measurement_ids
    )
    api_result = _philippine_collection(
        [selected_result], case["product_code"]
    ).model_dump(mode="json")["results"][0]
    return {
        **case,
        "device": {
            "device_id": device.device_id,
            "device_name": device.name,
            "device_friendly_name": device.friendly_name,
            "timezone": device.timezone,
        },
        "sensor": {
            "sensor_id": sensor.sensor_id,
            "external_sensor_id": sensor.external_sensor_id,
            "native_aggregation_period": selected_evaluation.sensor.aggregation_period,
            "input_unit_code": unit.code,
            "input_unit_symbol": unit.symbol,
        },
        "qualified_observation_counts": {
            "expected_hour_count": selected_evaluation.expected_hour_count,
            "valid_hour_count": selected_evaluation.valid_hour_count,
            "required_valid_hour_count": (
                selected_evaluation.required_valid_hour_count
            ),
            "block_valid_hour_counts": list(
                selected_evaluation.block_valid_hour_counts
            ),
            "maximum_consecutive_missing_hours": (
                selected_evaluation.maximum_consecutive_missing_hours
            ),
        },
        "concentration_result": {
            "normalized_concentration": (
                str(calculation.normalized_concentration)
                if calculation.normalized_concentration is not None
                else None
            ),
            "preprocessed_concentration": (
                str(calculation.preprocessed_concentration)
                if calculation.preprocessed_concentration is not None
                else None
            ),
            "normalized_unit": calculation.normalized_unit,
        },
        "aqi_result": {
            "numeric_value": (
                str(calculation.numeric_value)
                if calculation.numeric_value is not None
                else None
            ),
            "category_code": calculation.category_code,
            "category_label": calculation.category_label,
            "availability": (
                "available" if calculation.is_eligible else "unavailable"
            ),
            "calculation_status": calculation.calculation_status.value,
            "eligibility_status": selected_evaluation.eligibility_status,
            "coverage_status": selected_result.coverage_status,
            "exclusion_reason": (
                calculation.exclusion_reason.value
                if calculation.exclusion_reason is not None
                else selected_evaluation.exclusion_reason.value
                if selected_evaluation.exclusion_reason is not None
                else None
            ),
            "aqi_scale_status": (
                calculation.aqi_scale_status.value
                if calculation.aqi_scale_status is not None
                else None
            ),
        },
        "provenance": {
            "source_name": selected_result.source_name,
            "selected_sensor_reason": selected_result.selected_sensor_reason,
            "measurement_id_count": len(selected_result.measurement_ids),
            "measurement_ids_sha256": _measurement_id_sha256(
                selected_result.measurement_ids
            ),
            "duplicate_measurement_count": len(duplicate_ids),
            "rejected_measurement_count": len(rejected_ids),
            "off_frequency_measurement_count": len(off_frequency_ids),
        },
        "api_serialization": {
            "numeric_value": api_result["numeric_value"],
            "category_code": api_result["category_code"],
            "category_label": api_result["category_label"],
            "eligibility_status": api_result["eligibility_status"],
            "coverage_status": api_result["coverage_status"],
            "calculation_status": api_result["calculation_status"],
            "exclusion_reason": api_result["exclusion_reason"],
            "represented_local_date": api_result["represented_local_date"],
            "utc_window_started_at": api_result["utc_window_started_at"],
            "utc_window_ended_at": api_result["utc_window_ended_at"],
            "normalized_concentration": api_result["normalized_concentration"],
            "preprocessed_concentration": api_result[
                "preprocessed_concentration"
            ],
            "normalized_unit": api_result["normalized_unit"],
            "dominant_pollutants": api_result["dominant_pollutants"],
            "sensor_provenance": api_result["sensor_provenance"],
        },
    }


def _calculation_observation(calculation: Any) -> dict[str, Any]:
    from services.air_quality_index.philippines_denr import (
        PHILIPPINES_DENR_STANDARD,
    )

    category = next(
        (
            candidate
            for candidate in PHILIPPINES_DENR_STANDARD.categories
            if candidate.code == calculation.category_code
        ),
        None,
    )
    return {
        "normalized_concentration": (
            str(calculation.normalized_concentration)
            if calculation.normalized_concentration is not None
            else None
        ),
        "normalized_unit": calculation.normalized_unit,
        "preprocessed_concentration": (
            str(calculation.preprocessed_concentration)
            if calculation.preprocessed_concentration is not None
            else None
        ),
        "numeric_value": (
            str(calculation.numeric_value)
            if calculation.numeric_value is not None
            else None
        ),
        "category_code": calculation.category_code,
        "category_label": calculation.category_label,
        "category_color": category.color if category else None,
        "calculation_status": calculation.calculation_status.value,
        "eligibility_status": (
            "eligible" if calculation.is_eligible else "ineligible"
        ),
        "coverage_status": "complete" if calculation.is_eligible else "none",
        "exclusion_reason": (
            calculation.exclusion_reason.value
            if calculation.exclusion_reason is not None
            else None
        ),
        "aqi_scale_status": (
            calculation.aqi_scale_status.value
            if calculation.aqi_scale_status is not None
            else None
        ),
    }


def _synthetic_hourly_observation(valid_position_count: int) -> dict[str, Any]:
    from services.air_quality_index.hourly_measurements import (
        HourlySensorStreamMetadata,
        RawMeasurementInput,
    )
    from services.air_quality_index.philippines_denr_service import qualify_hour

    hour_start = datetime(2026, 8, 9, tzinfo=timezone.utc)
    sensor = HourlySensorStreamMetadata(
        sensor_id=1,
        external_sensor_id="synthetic-pm25",
        aggregation_period="2m",
        hourly_concentration_provenance=None,
        hourly_timestamp_semantics=None,
        expected_frequency_seconds=120,
        measurement_duration_seconds=120,
        source_aggregation_duration_seconds=120,
        measurement_timestamp_semantics="interval_end",
        measurement_metadata_status="provider_documented",
        measurement_metadata_managed_by="synthetic_review_fixture",
        input_unit_code="ug_m3",
        input_unit_symbol="µg/m³",
        parameter_code="pm25",
        device_id=1,
        device_name="Synthetic Manila device",
        device_friendly_name=None,
        latitude=None,
        longitude=None,
        device_timezone="Asia/Manila",
        source_name="Synthetic review fixture",
    )
    observations = [
        RawMeasurementInput(
            measurement_id=position,
            sensor_id=1,
            observed_at=hour_start + timedelta(minutes=2 * position),
            concentration=10,
            is_valid=True,
        )
        for position in range(1, valid_position_count + 1)
    ]
    result = qualify_hour(sensor, observations, interval_started_at=hour_start)
    return {
        "eligibility_status": result.eligibility_status,
        "coverage_status": "complete" if result.is_eligible else "none",
        "expected_observation_count": result.expected_observation_count,
        "valid_observation_count": result.valid_observation_count,
        "required_valid_observation_count": (
            result.required_valid_observation_count
        ),
        "exclusion_reason": (
            result.exclusion_reason.value if result.exclusion_reason else None
        ),
    }


def _synthetic_period_observation(
    source_evidence: dict[str, Any], *, rolling: bool
) -> dict[str, Any]:
    from services.air_quality_index.domain import ExclusionReason
    from services.air_quality_index.philippines_denr_service import (
        QualifiedPhilippineHour,
        qualify_completed_day_hours,
        qualify_rolling_eight_hour_hours,
    )

    count = int(source_evidence["expected_hour_count"])
    missing_positions = set(source_evidence.get("missing_hour_positions", []))
    if "valid_hour_positions" in source_evidence:
        valid_positions = set(source_evidence["valid_hour_positions"])
        missing_positions = set(range(count)) - valid_positions
    start = datetime(2026, 8, 9, tzinfo=timezone.utc)
    hours = tuple(
        QualifiedPhilippineHour(
            interval_started_at=start + timedelta(hours=position),
            interval_ended_at=start + timedelta(hours=position + 1),
            concentration=None if position in missing_positions else 10,
            normalized_unit="µg/m³",
            eligibility_status=(
                "ineligible" if position in missing_positions else "eligible"
            ),
            exclusion_reason=(
                ExclusionReason.MISSING_MEASUREMENTS
                if position in missing_positions
                else None
            ),
            expected_observation_count=1,
            valid_observation_count=0 if position in missing_positions else 1,
            required_valid_observation_count=1,
            measurement_ids=(),
            duplicate_measurement_ids=(),
            rejected_measurement_ids=(),
            off_frequency_measurement_ids=(),
        )
        for position in range(count)
    )
    result = (
        qualify_rolling_eight_hour_hours(hours)
        if rolling
        else qualify_completed_day_hours(hours)
    )
    observation = {
        "eligibility_status": result.eligibility_status,
        "coverage_status": (
            "complete" if result.eligibility_status == "eligible" else "none"
        ),
        "expected_hour_count": result.expected_hour_count,
        "valid_hour_count": result.valid_hour_count,
        "required_valid_hour_count": result.required_valid_hour_count,
        "exclusion_reason": (
            result.exclusion_reason.value if result.exclusion_reason else None
        ),
    }
    if not rolling:
        observation.update(
            {
                "block_valid_hour_counts": list(result.block_valid_hour_counts),
                "maximum_consecutive_missing_hours": (
                    result.maximum_consecutive_missing_hours
                ),
            }
        )
    return observation


def _synthetic_sensor_selection_observation(session: Any) -> dict[str, Any]:
    from sqlalchemy import select

    import models
    from services.air_quality_index.philippines_denr_service import (
        calculate_philippine_aqi_history,
    )

    parameter = session.scalar(
        select(models.Parameter).where(models.Parameter.code == "pm25")
    )
    unit = session.scalar(select(models.Unit).where(models.Unit.code == "ug_m3"))
    aggregation = session.scalar(
        select(models.AggregationPeriod).where(
            models.AggregationPeriod.code == "1h"
        )
    )
    device = models.Device(
        device_id=100001,
        name="Synthetic deterministic selection device",
        external_api_id="synthetic-review-device",
        manual_data_source_name="Synthetic review fixture",
        timezone="Asia/Manila",
    )
    session.add(device)
    from services.device_locations import set_device_location

    set_device_location(
        session, device, latitude=14.6, longitude=121.0
    )
    sensors = []
    for sensor_id, concentration in ((100011, 20), (100007, 10)):
        sensor = models.Sensor(
            sensor_id=sensor_id,
            device_id=device.device_id,
            external_sensor_id=f"synthetic-{sensor_id}",
            parameter_id=parameter.parameter_id,
            unit_id=unit.unit_id,
            aggregation_period_id=aggregation.aggregation_period_id,
            hourly_concentration_provenance="provider_reported_hourly_average",
            hourly_timestamp_semantics="hour_end",
            expected_frequency_seconds=3600,
            measurement_duration_seconds=3600,
            source_aggregation_duration_seconds=3600,
            measurement_timestamp_semantics="interval_end",
            measurement_metadata_status="provider_documented",
            measurement_metadata_managed_by="synthetic_review_fixture",
        )
        session.add(sensor)
        sensors.append((sensor, concentration))
    session.flush()
    utc_start = datetime(2026, 8, 1, 16, tzinfo=timezone.utc)
    for sensor, concentration in sensors:
        session.add_all(
            models.Measurement(
                sensor_id=sensor.sensor_id,
                observed_at=utc_start + timedelta(hours=position),
                value=concentration,
                is_valid=True,
            )
            for position in range(1, 25)
        )
    session.flush()
    result = next(
        item
        for item in calculate_philippine_aqi_history(
            session,
            product_code="philippines_denr.pm25.completed_day",
            start_utc=utc_start,
            end_utc=utc_start + timedelta(days=1, microseconds=1),
            device_id=device.device_id,
            limit=10,
        )
        if item.represented_local_date.isoformat() == "2026-08-02"
    )
    return {
        "eligibility_status": (
            "eligible" if result.calculation.is_eligible else "ineligible"
        ),
        "coverage_status": result.coverage_status,
        "selected_sensor_id": result.selected_sensor_id,
        "selected_sensor_reason": result.selected_sensor_reason,
        "exclusion_reason": (
            result.calculation.exclusion_reason.value
            if result.calculation.exclusion_reason
            else None
        ),
    }


def _synthetic_case_observations(
    session: Any, synthetic_candidates: dict[str, Any]
) -> list[dict[str, Any]]:
    from services.air_quality_index.philippines_denr import (
        calculate_component_aqi,
        calculate_ozone_aqi,
    )

    observations = []
    for candidate in synthetic_candidates["cases"]:
        evidence = candidate["source_evidence"]
        case_kind = candidate["case_kind"]
        if candidate["component_code"] == "ozone_latest_completed_window":
            calculation = calculate_ozone_aqi(
                evidence["eight_hour_concentration"],
                evidence["eight_hour_input_unit"],
                corresponding_one_hour_concentration=evidence[
                    "one_hour_concentration"
                ],
                corresponding_one_hour_input_unit=evidence["one_hour_input_unit"],
            )
            result = _calculation_observation(calculation)
        elif candidate["component_code"] != "temporal_qualification":
            calculation = calculate_component_aqi(
                candidate["parameter_code"],
                candidate["component_code"],
                evidence["synthetic_concentration"],
                evidence["input_unit"],
            )
            result = _calculation_observation(calculation)
        elif case_kind == "hourly_completeness":
            result = _synthetic_hourly_observation(
                int(evidence["valid_position_count"])
            )
        elif case_kind == "rolling_completeness":
            result = _synthetic_period_observation(evidence, rolling=True)
        elif case_kind in {"daily_completeness", "missing_data"}:
            result = _synthetic_period_observation(evidence, rolling=False)
        elif case_kind == "sensor_selection":
            result = _synthetic_sensor_selection_observation(session)
        else:
            raise ValueError(f"Unsupported synthetic case kind: {case_kind}")
        observations.append(
            {
                "case_id": candidate["case_id"],
                "case_kind": case_kind,
                "parameter_code": candidate["parameter_code"],
                "component_code": candidate["component_code"],
                "source_evidence": evidence,
                "production_result": result,
            }
        )
    return observations


def build_philippine_observation_report(
    *,
    database_path: Path,
    public_root: Path,
    restricted_root: Path,
    synthetic_candidate_path: Path | None = None,
) -> dict[str, Any]:
    database_url = f"sqlite+pysqlite:///{database_path.resolve().as_posix()}"
    with (
        _temporary_environment("DATABASE_URL", database_url),
        _temporary_environment("COMPASSAQ_ENV", "test"),
        _temporary_environment("ENABLE_PAID_API_IMPORTS", "false"),
    ):
        _upgrade_empty_database(database_url)
        if str(BACKEND_ROOT) not in sys.path:
            sys.path.insert(0, str(BACKEND_ROOT))

        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from sqlalchemy.pool import NullPool

        from reference_data.loader import load_reference_fixture

        engine = create_engine(database_url, poolclass=NullPool)
        try:
            with Session(engine) as session:
                _seed_reference_metadata(session)
                fixture_summaries = {
                    "openaq": load_reference_fixture(session, public_root),
                    "purpleair": load_reference_fixture(session, restricted_root),
                }
                cases = [
                    _case_observation(session, fixture_summaries, case)
                    for case in REAL_CASES
                ]
                synthetic_cases = []
                if synthetic_candidate_path is not None:
                    synthetic_candidates = json.loads(
                        synthetic_candidate_path.read_text(encoding="utf-8")
                    )
                    synthetic_cases = _synthetic_case_observations(
                        session, synthetic_candidates
                    )
        finally:
            engine.dispose()

    return {
        "schema_version": "philippines-denr-implementation-observations-1",
        "artifact_kind": "implementation_observations",
        "oracle_status": "not_expected_results",
        "methodology_code": "philippines_denr_aqi",
        "methodology_version": "denr_emb_aqi_2021",
        "database_creation": (
            "alembic_autogenerated_current_orm_schema_on_empty_temporary_sqlite_"
            "stamped_at_production_head"
        ),
        "safety": {
            "provider_calls": 0,
            "credential_reads": 0,
            "purpleair_points_consumed": 0,
            "paid_imports_enabled": False,
        },
        "cases": cases,
        "synthetic_cases": synthetic_cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--public-root",
        type=Path,
        default=DEFAULT_REFERENCE_ROOT / "public" / "openaq",
    )
    parser.add_argument(
        "--restricted-root",
        type=Path,
        default=DEFAULT_REFERENCE_ROOT / "restricted" / "purpleair",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--synthetic-candidates", type=Path)
    parser.add_argument("--expected-root", type=Path, default=DEFAULT_EXPECTED_ROOT)
    args = parser.parse_args()
    output_path = args.output.resolve()
    if _is_within(output_path, args.expected_root.resolve()):
        raise CurrentObservationError(
            "Current Philippine observations cannot be written inside expected results"
        )
    with tempfile.TemporaryDirectory(
        prefix="compassaq-philippines-conformance-"
    ) as temporary_directory:
        report = build_philippine_observation_report(
            database_path=Path(temporary_directory) / "observations.sqlite3",
            public_root=args.public_root.resolve(),
            restricted_root=args.restricted_root.resolve(),
            synthetic_candidate_path=(
                args.synthetic_candidates.resolve()
                if args.synthetic_candidates is not None
                else None
            ),
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
