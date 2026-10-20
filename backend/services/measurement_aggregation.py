"""Authoritative ordinary measurement aggregation capability and execution.

This module deliberately does not implement AQI completeness or regulatory
input construction.  It answers only whether stored measurement streams can be
rolled up through configured ``ParameterAggregationRollup`` edges and performs
those ordinary averages.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import case, func, literal, select
from sqlalchemy.orm import Session, aliased

from models import (
    AggregationPeriod,
    Device,
    ExternalAPI,
    Measurement,
    Parameter,
    ParameterAggregationRollup,
    Sensor,
    Unit,
)
from services.data_attribution import serialize_data_attribution
from services.device_locations import device_bbox_predicate
from utils.parameter_aggregation_rule_formatting import (
    ParameterAggregationRuleFormatting,
    apply_parameter_aggregation_rule,
    load_parameter_aggregation_rules,
    parameter_aggregation_display_precision,
    resolve_parameter_aggregation_rule,
)


MANUAL_SOURCE_LABEL = "Other"


class MeasurementAggregationError(ValueError):
    """A requested ordinary measurement aggregation cannot be resolved."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class AggregationPeriodDefinition:
    code: str
    display_name: str
    duration_minutes: Optional[int]
    is_rolling: bool


@dataclass(frozen=True)
class ResolvedAggregationPath:
    parameter_code: str
    native_aggregation_code: Optional[str]
    result_aggregation_code: str
    path: tuple[str, ...]
    capability_kind: str
    result_period: Optional[AggregationPeriodDefinition]


@dataclass(frozen=True)
class MeasurementAggregationPoint:
    measurement_id: int
    sensor_id: int
    value: Optional[float]
    observed_at: Optional[datetime]
    interval_started_at: Optional[datetime]
    interval_ended_at: Optional[datetime]
    sample_count: int
    valid_sample_count: int
    invalid_sample_count: int
    native_aggregation_code: Optional[str]
    result_aggregation_code: str
    formatting_status: str
    display_precision: Optional[int]
    qc_flags: Optional[dict]
    latest_source_observed_at: Optional[datetime] = None
    query_since: Optional[datetime] = None
    result_is_rolling: bool = False


def _normalize_code(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _normalize_datetime(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _load_periods(session: Session) -> dict[str, AggregationPeriodDefinition]:
    rows = session.execute(
        select(
            AggregationPeriod.code,
            AggregationPeriod.display_name,
            AggregationPeriod.duration_minutes,
            AggregationPeriod.is_rolling,
        )
    ).all()
    return {
        _normalize_code(row.code): AggregationPeriodDefinition(
            code=_normalize_code(row.code),
            display_name=row.display_name,
            duration_minutes=row.duration_minutes,
            is_rolling=bool(row.is_rolling),
        )
        for row in rows
    }


def _load_edges(session: Session, parameter_code: str) -> set[tuple[str, str]]:
    source_period = aliased(AggregationPeriod, name="measurement_rollup_source")
    target_period = aliased(AggregationPeriod, name="measurement_rollup_target")
    rows = session.execute(
        select(source_period.code, target_period.code)
        .select_from(ParameterAggregationRollup)
        .join(Parameter, Parameter.parameter_id == ParameterAggregationRollup.parameter_id)
        .join(
            source_period,
            source_period.aggregation_period_id
            == ParameterAggregationRollup.from_aggregation_period_id,
        )
        .join(
            target_period,
            target_period.aggregation_period_id
            == ParameterAggregationRollup.to_aggregation_period_id,
        )
        .where(func.lower(Parameter.code) == _normalize_code(parameter_code))
    ).all()
    return {(_normalize_code(row[0]), _normalize_code(row[1])) for row in rows}


def _edge_is_valid(
    source_code: str,
    target_code: str,
    periods: dict[str, AggregationPeriodDefinition],
) -> bool:
    source = periods.get(source_code)
    target = periods.get(target_code)
    if source is None or target is None:
        return False
    if source.duration_minutes is None or target.duration_minutes is None:
        return False
    if source.duration_minutes <= 0 or target.duration_minutes <= 0:
        return False
    return target.duration_minutes > source.duration_minutes


def _has_reachable_cycle(start_code: str, edges: set[tuple[str, str]]) -> bool:
    adjacency: dict[str, list[str]] = {}
    for source_code, target_code in edges:
        adjacency.setdefault(source_code, []).append(target_code)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(current_code: str) -> bool:
        if current_code in visiting:
            return True
        if current_code in visited:
            return False
        visiting.add(current_code)
        for target_code in adjacency.get(current_code, []):
            if visit(target_code):
                return True
        visiting.remove(current_code)
        visited.add(current_code)
        return False

    return visit(start_code)


def _configured_path_exists(
    source_code: str,
    target_code: str,
    edges: set[tuple[str, str]],
) -> bool:
    adjacency: dict[str, list[str]] = {}
    for edge_source, edge_target in edges:
        adjacency.setdefault(edge_source, []).append(edge_target)
    pending = [source_code]
    visited: set[str] = set()
    while pending:
        current_code = pending.pop()
        if current_code in visited:
            continue
        visited.add(current_code)
        for next_code in adjacency.get(current_code, []):
            if next_code == target_code:
                return True
            pending.append(next_code)
    return False


def _resolve_measurement_aggregation(
    parameter_code: str,
    native_aggregation_code: Optional[str],
    requested_aggregation_code: str,
    periods: dict[str, AggregationPeriodDefinition],
    configured_edges: set[tuple[str, str]],
) -> ResolvedAggregationPath:
    parameter = _normalize_code(parameter_code)
    native = _normalize_code(native_aggregation_code) or None
    requested = _normalize_code(requested_aggregation_code)
    if requested in {"raw", "latest"}:
        requested = native or "raw"

    if native is None:
        if requested == "raw":
            return ResolvedAggregationPath(parameter, None, "raw", ("raw",), "native", None)
        raise MeasurementAggregationError(
            "unknown_native_aggregation",
            "The sensor's native aggregation period is unknown; only raw observations are available.",
        )

    native_period = periods.get(native)
    if native_period is None:
        raise MeasurementAggregationError(
            "unknown_native_aggregation",
            f"Unknown native aggregation period '{native}'.",
        )
    if requested == native:
        return ResolvedAggregationPath(
            parameter, native, native, (native,), "native", native_period
        )
    if requested not in periods:
        raise MeasurementAggregationError(
            "unknown_result_aggregation",
            f"Unknown result aggregation period '{requested}'.",
        )

    if (native, requested) in configured_edges and not _edge_is_valid(
        native, requested, periods
    ):
        raise MeasurementAggregationError(
            "invalid_rollup_duration",
            f"Configured rollup {native} to {requested} must increase a known positive duration.",
        )

    edges = {
        edge for edge in configured_edges
        if _edge_is_valid(edge[0], edge[1], periods)
    }
    if (native, requested) in edges:
        return ResolvedAggregationPath(
            parameter,
            native,
            requested,
            (native, requested),
            "direct_rollup",
            periods[requested],
        )

    adjacency: dict[str, list[str]] = {}
    for source_code, target_code in sorted(edges):
        adjacency.setdefault(source_code, []).append(target_code)

    paths: list[tuple[str, ...]] = []

    def visit(current: str, path: tuple[str, ...]) -> None:
        for target in adjacency.get(current, []):
            if target in path:
                continue
            next_path = (*path, target)
            if target == requested:
                paths.append(next_path)
            else:
                visit(target, next_path)

    visit(native, (native,))
    if not paths:
        if _has_reachable_cycle(native, configured_edges):
            raise MeasurementAggregationError(
                "cyclic_rollup_path",
                f"Configured rollups reachable from {native} contain a cycle for {parameter}.",
            )
        if _configured_path_exists(native, requested, configured_edges):
            raise MeasurementAggregationError(
                "invalid_rollup_duration",
                f"A configured path from {native} to {requested} contains a non-increasing or unknown duration.",
            )
        raise MeasurementAggregationError(
            "unsupported_measurement_aggregation",
            f"Aggregation from {native} to {requested} is not configured for {parameter}.",
        )
    if len(paths) > 1:
        raise MeasurementAggregationError(
            "ambiguous_rollup_path",
            f"More than one configured rollup path reaches {requested} from {native} for {parameter}.",
        )
    return ResolvedAggregationPath(
        parameter,
        native,
        requested,
        paths[0],
        "chained_rollup",
        periods[requested],
    )


def resolve_measurement_aggregation(
    session: Session,
    parameter_code: str,
    native_aggregation_code: Optional[str],
    requested_aggregation_code: str,
) -> ResolvedAggregationPath:
    """Resolve one native/direct/chained ordinary measurement aggregation.

    Direct edges intentionally take precedence. Without a direct edge, the
    target must have exactly one valid configured path from the native period.
    """

    return _resolve_measurement_aggregation(
        parameter_code,
        native_aggregation_code,
        requested_aggregation_code,
        _load_periods(session),
        _load_edges(session, parameter_code),
    )


def _load_exact_rule(
    session: Session,
    parameter_code: str,
    result_aggregation_code: str,
) -> Optional[ParameterAggregationRuleFormatting]:
    rules = load_parameter_aggregation_rules(
        session, parameter_code, {result_aggregation_code}
    )
    return resolve_parameter_aggregation_rule(rules, result_aggregation_code)


def _bucket_start_expression(timestamp_expression, bucket_seconds: int, dialect: str):
    if dialect == "sqlite":
        epoch_seconds = func.strftime("%s", timestamp_expression)
        bucket_epoch = func.floor(epoch_seconds / bucket_seconds) * bucket_seconds
        return func.datetime(bucket_epoch, "unixepoch")
    epoch_seconds = func.extract("epoch", timestamp_expression)
    bucket_epoch = func.floor(epoch_seconds / bucket_seconds) * bucket_seconds
    return func.to_timestamp(bucket_epoch)


def _as_utc_datetime(value: object) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return _normalize_datetime(value)


def execute_measurement_aggregation(
    session: Session,
    *,
    sensor_ids: Iterable[int],
    parameter_code: str,
    native_aggregation_code: Optional[str],
    result_aggregation_code: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    include_invalid: bool = False,
    latest_only: bool = False,
) -> list[MeasurementAggregationPoint]:
    """Calculate one resolved path for one native-period sensor group."""

    normalized_sensor_ids = sorted({int(sensor_id) for sensor_id in sensor_ids})
    if not normalized_sensor_ids:
        return []
    timestamp_metadata_rows = session.execute(
        select(
            Sensor.sensor_id,
            Sensor.measurement_duration_seconds,
            Sensor.measurement_timestamp_semantics,
        ).where(Sensor.sensor_id.in_(normalized_sensor_ids))
    ).all()
    timestamp_metadata_by_sensor = {
        int(row.sensor_id): row for row in timestamp_metadata_rows
    }
    resolved = resolve_measurement_aggregation(
        session, parameter_code, native_aggregation_code, result_aggregation_code
    )
    since_utc = _normalize_datetime(since)
    until_utc = _normalize_datetime(until)
    if since_utc is not None and until_utc is not None and since_utc > until_utc:
        raise MeasurementAggregationError(
            "reversed_date_range", "The requested start must not be after the end."
        )

    final_rule = _load_exact_rule(
        session, resolved.parameter_code, resolved.result_aggregation_code
    )
    formatting_status = "configured" if final_rule is not None else "not_configured"
    display_precision = parameter_aggregation_display_precision(final_rule)

    base = select(
        Measurement.measurement_id.label("measurement_id"),
        Measurement.sensor_id.label("sensor_id"),
        Measurement.value.label("value"),
        Measurement.observed_at.label("observed_at"),
        Measurement.observed_at.label("latest_source_observed_at"),
        literal(1).label("sample_count"),
        case((Measurement.is_valid.is_(True), 1), else_=0).label("valid_sample_count"),
        case((Measurement.is_valid.is_(False), 1), else_=0).label("invalid_sample_count"),
        Measurement.qc_flags.label("qc_flags"),
    ).where(Measurement.sensor_id.in_(normalized_sensor_ids))
    if since_utc is not None:
        base = base.where(Measurement.observed_at >= since_utc)
    if until_utc is not None:
        base = base.where(Measurement.observed_at <= until_utc)
    if (
        len(resolved.path) > 1
        and resolved.result_period is not None
        and resolved.result_period.is_rolling
        and latest_only
    ):
        # Resolve one rolling evaluation instant and bound raw observations before
        # fixed-hour aggregation. A missing 'until' must never admit future rows.
        rolling_end = until_utc or datetime.now(timezone.utc)
        rolling_start = rolling_end - timedelta(
            minutes=resolved.result_period.duration_minutes or 0
        )
        base = base.where(
            Measurement.observed_at > rolling_start,
            Measurement.observed_at <= rolling_end,
        )
    if not include_invalid:
        base = base.where(Measurement.is_valid.is_(True))
    current = base.subquery("measurement_aggregation_base")

    dialect = session.bind.dialect.name if session.bind is not None else "postgresql"
    is_native = len(resolved.path) == 1
    result_period = resolved.result_period

    if not is_native and result_period is not None and result_period.is_rolling:
        if not latest_only:
            raise MeasurementAggregationError(
                "rolling_history_not_supported",
                "Rolling measurement aggregations are available only for latest results.",
            )
        # The raw query already uses (rolling_start, evaluation_end]. Do not
        # filter fixed-hour labels here: an hour beginning before rolling_start
        # can still contain eligible observations inside the rolling window.
        evaluation_end = rolling_end

        # Build all configured fixed stages before the final rolling edge.
        for stage_code in resolved.path[1:-1]:
            stage = _load_periods(session)[stage_code]
            bucket_seconds = int(stage.duration_minutes or 0) * 60
            bucket_start = _bucket_start_expression(current.c.observed_at, bucket_seconds, dialect)
            current = (
                select(
                    current.c.sensor_id,
                    func.avg(current.c.value).label("value"),
                    bucket_start.label("observed_at"),
                    func.max(current.c.latest_source_observed_at).label("latest_source_observed_at"),
                    func.sum(current.c.sample_count).label("sample_count"),
                    func.sum(current.c.valid_sample_count).label("valid_sample_count"),
                    func.sum(current.c.invalid_sample_count).label("invalid_sample_count"),
                )
                .group_by(current.c.sensor_id, bucket_start)
                .subquery(f"measurement_aggregation_{stage_code}")
            )
        query = (
            select(
                literal(0).label("measurement_id"),
                current.c.sensor_id,
                func.avg(current.c.value).label("value"),
                literal(evaluation_end).label("observed_at"),
                func.max(current.c.latest_source_observed_at).label("latest_source_observed_at"),
                func.sum(current.c.sample_count).label("sample_count"),
                func.sum(current.c.valid_sample_count).label("valid_sample_count"),
                func.sum(current.c.invalid_sample_count).label("invalid_sample_count"),
                literal(None).label("qc_flags"),
            )
            .group_by(current.c.sensor_id)
        )
    else:
        periods = _load_periods(session)
        for stage_code in resolved.path[1:]:
            stage = periods[stage_code]
            bucket_seconds = int(stage.duration_minutes or 0) * 60
            bucket_start = _bucket_start_expression(current.c.observed_at, bucket_seconds, dialect)
            current = (
                select(
                    current.c.sensor_id,
                    func.avg(current.c.value).label("value"),
                    bucket_start.label("observed_at"),
                    func.sum(current.c.sample_count).label("sample_count"),
                    func.sum(current.c.valid_sample_count).label("valid_sample_count"),
                    func.sum(current.c.invalid_sample_count).label("invalid_sample_count"),
                )
                .group_by(current.c.sensor_id, bucket_start)
                .subquery(f"measurement_aggregation_{stage_code}")
            )

        if latest_only:
            ranked = select(
                current,
                func.row_number().over(
                    partition_by=current.c.sensor_id,
                    order_by=current.c.observed_at.desc(),
                ).label("row_number"),
            ).subquery("measurement_aggregation_ranked")
            query = select(
                (ranked.c.measurement_id if is_native else literal(0)).label("measurement_id"),
                ranked.c.sensor_id,
                ranked.c.value,
                ranked.c.observed_at,
                ranked.c.sample_count,
                ranked.c.valid_sample_count,
                ranked.c.invalid_sample_count,
                (ranked.c.qc_flags if is_native else literal(None)).label("qc_flags"),
            ).where(ranked.c.row_number == 1)
        else:
            query = select(
                (current.c.measurement_id if is_native else literal(0)).label("measurement_id"),
                current.c.sensor_id,
                current.c.value,
                current.c.observed_at,
                current.c.sample_count,
                current.c.valid_sample_count,
                current.c.invalid_sample_count,
                (current.c.qc_flags if is_native else literal(None)).label("qc_flags"),
            ).order_by(current.c.sensor_id, current.c.observed_at)

    rows = session.execute(query).all()
    points: list[MeasurementAggregationPoint] = []
    for row in rows:
        observed_at = _as_utc_datetime(row.observed_at)
        interval_start = observed_at
        interval_end = observed_at
        computed_rolling = not is_native and result_period is not None and result_period.is_rolling
        if computed_rolling:
            interval_start = rolling_start
            interval_end = rolling_end
        if observed_at is not None and result_period is not None and not result_period.is_rolling:
            interval_end = observed_at + timedelta(minutes=result_period.duration_minutes or 0)
        if is_native and observed_at is not None:
            timestamp_metadata = timestamp_metadata_by_sensor.get(int(row.sensor_id))
            timestamp_semantics = (
                timestamp_metadata.measurement_timestamp_semantics
                if timestamp_metadata is not None
                else None
            )
            if timestamp_semantics not in {"interval_start", "interval_end"}:
                # These provider timestamps identify an instant, not a measured
                # interval boundary, or their meaning is unknown. Publishing a
                # fabricated interval would make the source measurement easier
                # to misinterpret.
                interval_start = None
                interval_end = None
            elif timestamp_semantics == "interval_end":
                duration_seconds = (
                    timestamp_metadata.measurement_duration_seconds
                    if timestamp_metadata is not None
                    else None
                )
                if duration_seconds is None and result_period is not None:
                    duration_seconds = int(result_period.duration_minutes or 0) * 60
                if duration_seconds is not None and duration_seconds > 0:
                    interval_start = observed_at - timedelta(seconds=duration_seconds)
                    interval_end = observed_at
        raw_value = float(row.value) if row.value is not None else None
        formatted_value = raw_value
        # A native result is the stored scientific observation, including a
        # provider's own hourly/daily product. Keep its value intact and expose
        # the rule only as display metadata. Apply numeric processing only to
        # products calculated here through a rollup path.
        if not is_native and final_rule is not None:
            formatted_value = apply_parameter_aggregation_rule(
                raw_value,
                final_rule.rounding_method,
                final_rule.rounding_precision,
                final_rule.truncation_method,
                final_rule.truncation_precision,
            )
        points.append(
            MeasurementAggregationPoint(
                measurement_id=int(row.measurement_id or 0),
                sensor_id=int(row.sensor_id),
                value=formatted_value,
                observed_at=observed_at,
                interval_started_at=interval_start,
                interval_ended_at=interval_end,
                sample_count=int(row.sample_count or 0),
                valid_sample_count=int(row.valid_sample_count or 0),
                invalid_sample_count=int(row.invalid_sample_count or 0),
                native_aggregation_code=resolved.native_aggregation_code,
                result_aggregation_code=resolved.result_aggregation_code,
                formatting_status=formatting_status,
                display_precision=display_precision,
                qc_flags=row.qc_flags,
                latest_source_observed_at=(
                    _as_utc_datetime(row.latest_source_observed_at) if computed_rolling else None
                ),
                query_since=since_utc if computed_rolling else None,
                result_is_rolling=bool(computed_rolling),
            )
        )
    return points


def load_measurement_aggregation_capabilities(
    session: Session,
    *,
    parameter_code: Optional[str] = None,
    source: Optional[str] = None,
    native_aggregation_code: Optional[str] = None,
) -> list[dict]:
    """Return backend-resolved aggregation options for native stream groups."""

    native_period = aliased(AggregationPeriod, name="capability_native_period")
    query = (
        select(Parameter.code, native_period.code)
        .select_from(Sensor)
        .join(Parameter, Parameter.parameter_id == Sensor.parameter_id)
        .join(Device, Device.device_id == Sensor.device_id)
        .outerjoin(ExternalAPI, ExternalAPI.external_api_id == Device.external_api_id)
        .outerjoin(native_period, native_period.aggregation_period_id == Sensor.aggregation_period_id)
        .distinct()
    )
    if parameter_code:
        query = query.where(func.lower(Parameter.code) == _normalize_code(parameter_code))
    if native_aggregation_code:
        query = query.where(func.lower(native_period.code) == _normalize_code(native_aggregation_code))
    normalized_source = _normalize_code(source)
    if normalized_source == MANUAL_SOURCE_LABEL.lower():
        query = query.where(Device.manual_data_source_name.is_not(None))
    elif normalized_source:
        query = query.where(
            Device.manual_data_source_name.is_(None),
            func.lower(ExternalAPI.name) == normalized_source,
        )

    native_groups = session.execute(query).all()
    periods = _load_periods(session)
    parameter_codes = {_normalize_code(row[0]) for row in native_groups}
    edges_by_parameter = {
        parameter: _load_edges(session, parameter) for parameter in parameter_codes
    }
    results: list[dict] = []
    for row in native_groups:
        parameter = _normalize_code(row[0])
        native = _normalize_code(row[1]) or None
        if native is None:
            results.append(
                {
                    "parameter_code": parameter,
                    "native_aggregation_code": None,
                    "native_status": "unknown",
                    "supported_aggregations": [
                        {
                            "result_aggregation_code": "raw",
                            "display_name": "Raw/latest (native period unknown)",
                            "duration_minutes": None,
                            "is_rolling": False,
                            "capability_kind": "native",
                            "rollup_path": ["raw"],
                            "supports_latest": True,
                            "supports_history": True,
                            "formatting_status": "not_configured",
                            "display_precision": None,
                        }
                    ],
                    "diagnostics": [],
                }
            )
            continue

        candidate_codes = [native, *periods.keys()]
        supported: list[dict] = []
        diagnostics: list[dict] = []
        seen: set[str] = set()
        for candidate in candidate_codes:
            if candidate in seen:
                continue
            seen.add(candidate)
            try:
                resolved = _resolve_measurement_aggregation(
                    parameter,
                    native,
                    candidate,
                    periods,
                    edges_by_parameter.get(parameter, set()),
                )
            except MeasurementAggregationError as exc:
                if exc.reason != "unsupported_measurement_aggregation":
                    diagnostics.append(
                        {
                            "result_aggregation_code": candidate,
                            "reason": exc.reason,
                            "message": str(exc),
                        }
                    )
                continue
            period = resolved.result_period
            rule = _load_exact_rule(session, parameter, resolved.result_aggregation_code)
            supported.append(
                {
                    "result_aggregation_code": resolved.result_aggregation_code,
                    "display_name": period.display_name if period else resolved.result_aggregation_code,
                    "duration_minutes": period.duration_minutes if period else None,
                    "is_rolling": bool(period.is_rolling) if period else False,
                    "capability_kind": resolved.capability_kind,
                    "rollup_path": list(resolved.path),
                    "supports_latest": True,
                    "supports_history": not bool(period.is_rolling) if period else True,
                    "formatting_status": "configured" if rule is not None else "not_configured",
                    "display_precision": parameter_aggregation_display_precision(rule),
                }
            )
        supported.sort(
            key=lambda item: (
                item["duration_minutes"] is None,
                item["duration_minutes"] or 0,
                item["result_aggregation_code"],
            )
        )
        results.append(
            {
                "parameter_code": parameter,
                "native_aggregation_code": native,
                "native_status": "known",
                "supported_aggregations": supported,
                "diagnostics": diagnostics,
            }
        )

    results.sort(key=lambda item: (item["parameter_code"], item["native_aggregation_code"] or ""))
    return results


def supported_native_periods_for_target(
    session: Session,
    parameter_code: str,
    result_aggregation_code: str,
) -> set[str]:
    """Return known native periods that can produce the requested result."""

    periods = _load_periods(session)
    supported: set[str] = set()
    for native_code in periods:
        try:
            resolve_measurement_aggregation(
                session, parameter_code, native_code, result_aggregation_code
            )
        except MeasurementAggregationError:
            continue
        supported.add(native_code)
    return supported


def execute_latest_measurements(
    session: Session,
    *,
    result_aggregation_code: Optional[str] = None,
    parameter_code: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    source: Optional[str] = None,
    device_id: Optional[int] = None,
    bbox: Optional[tuple[float, float, float, float]] = None,
) -> list[dict]:
    """Return latest ordinary results using one execution path per stream group."""

    native_period = aliased(AggregationPeriod, name="latest_native_period")
    metadata_query = (
        select(
            Sensor.sensor_id,
            Sensor.external_sensor_id,
            Parameter.code.label("parameter_code"),
            Parameter.display_name.label("parameter_name"),
            Unit.symbol.label("unit_symbol"),
            native_period.code.label("native_aggregation_code"),
            Device.device_id,
            Device.name.label("device_name"),
            Device.friendly_name.label("device_friendly_name"),
            Device.latitude,
            Device.longitude,
            Device.timezone,
            Device.manual_data_source_name,
            ExternalAPI.name.label("external_api_name"),
            Device.acquisition_path,
            Device.hardware_provider_name,
            Device.provider_url,
            Device.contributor_name,
            Device.contributor_url,
            Device.license_code,
            Device.license_url,
            Device.license_share_alike,
        )
        .select_from(Sensor)
        .join(Parameter, Parameter.parameter_id == Sensor.parameter_id)
        .outerjoin(Unit, Unit.unit_id == Sensor.unit_id)
        .join(Device, Device.device_id == Sensor.device_id)
        .outerjoin(ExternalAPI, ExternalAPI.external_api_id == Device.external_api_id)
        .outerjoin(native_period, native_period.aggregation_period_id == Sensor.aggregation_period_id)
    )
    if parameter_code:
        metadata_query = metadata_query.where(
            func.lower(Parameter.code) == _normalize_code(parameter_code)
        )
    if device_id is not None:
        metadata_query = metadata_query.where(Device.device_id == device_id)
    normalized_source = _normalize_code(source)
    if normalized_source == MANUAL_SOURCE_LABEL.lower():
        metadata_query = metadata_query.where(Device.manual_data_source_name.is_not(None))
    elif normalized_source:
        metadata_query = metadata_query.where(
            Device.manual_data_source_name.is_(None),
            func.lower(ExternalAPI.name) == normalized_source,
        )
    if bbox is not None:
        metadata_query = metadata_query.where(
            device_bbox_predicate(Device.location, bbox)
        )

    metadata_rows = session.execute(metadata_query).all()
    metadata_by_sensor = {int(row.sensor_id): row for row in metadata_rows}
    stream_groups: dict[tuple[str, Optional[str]], list[int]] = {}
    for row in metadata_rows:
        parameter = _normalize_code(row.parameter_code)
        native = _normalize_code(row.native_aggregation_code) or None
        stream_groups.setdefault((parameter, native), []).append(int(row.sensor_id))

    grouped_sensor_ids: dict[tuple[str, Optional[str], str], list[int]] = {}
    for (parameter, native), sensor_ids in stream_groups.items():
        requested = _normalize_code(result_aggregation_code) or (native or "raw")
        try:
            resolved = resolve_measurement_aggregation(session, parameter, native, requested)
        except MeasurementAggregationError:
            continue
        group_key = (parameter, native, resolved.result_aggregation_code)
        grouped_sensor_ids[group_key] = sensor_ids

    results: list[dict] = []
    for (parameter, native, requested), sensor_ids in grouped_sensor_ids.items():
        points = execute_measurement_aggregation(
            session,
            sensor_ids=sensor_ids,
            parameter_code=parameter,
            native_aggregation_code=native,
            result_aggregation_code=requested,
            since=since,
            until=until,
            include_invalid=False,
            latest_only=True,
        )
        for point in points:
            metadata = metadata_by_sensor[point.sensor_id]
            public_source_name = (
                MANUAL_SOURCE_LABEL
                if metadata.manual_data_source_name
                else metadata.external_api_name
            )
            results.append(
                {
                    "measurement_id": point.measurement_id,
                    "sensor_id": point.sensor_id,
                    "external_sensor_id": metadata.external_sensor_id,
                    "parameter": parameter,
                    "parameter_name": metadata.parameter_name,
                    "value": point.value,
                    "unit": metadata.unit_symbol,
                    "observed_at": point.observed_at.isoformat() if point.observed_at else None,
                    "result_is_rolling": point.result_is_rolling,
                    "latest_source_observed_at": (
                        point.latest_source_observed_at.isoformat() if point.latest_source_observed_at else None
                    ),
                    "query_since": point.query_since.isoformat() if point.query_since else None,
                    "sensor_aggregation_period": native,
                    "native_aggregation_code": native,
                    "result_aggregation_code": point.result_aggregation_code,
                    "formatting_status": point.formatting_status,
                    "display_precision": point.display_precision,
                    "interval_started_at": (
                        point.interval_started_at.isoformat() if point.interval_started_at else None
                    ),
                    "interval_ended_at": (
                        point.interval_ended_at.isoformat() if point.interval_ended_at else None
                    ),
                    "sample_count": point.sample_count,
                    "valid_sample_count": point.valid_sample_count,
                    "invalid_sample_count": point.invalid_sample_count,
                    "device": {
                        "device_id": metadata.device_id,
                        "name": metadata.device_name,
                        "friendly_name": metadata.device_friendly_name,
                        "latitude": metadata.latitude,
                        "longitude": metadata.longitude,
                        "timezone": metadata.timezone,
                        "network": public_source_name,
                        "external_api": (
                            {"name": public_source_name} if public_source_name is not None else None
                        ),
                        "data_attribution": serialize_data_attribution(
                            acquisition_path=metadata.acquisition_path,
                            data_provider_name=public_source_name,
                            hardware_provider_name=metadata.hardware_provider_name,
                            provider_url=metadata.provider_url,
                            contributor_name=metadata.contributor_name,
                            contributor_url=metadata.contributor_url,
                            license_code=metadata.license_code,
                            license_url=metadata.license_url,
                            license_share_alike=metadata.license_share_alike,
                        ),
                    },
                }
            )

    # Units are sensor-owned and do not change during ordinary aggregation.
    if results:
        units = dict(
            session.execute(
                select(Sensor.sensor_id, Unit.symbol)
                .outerjoin(Unit, Unit.unit_id == Sensor.unit_id)
                .where(Sensor.sensor_id.in_([row["sensor_id"] for row in results]))
            ).all()
        )
        for result in results:
            result["unit"] = units.get(result["sensor_id"])
    # Compatibility routes apply their limits after this shared call. Keep the
    # global latest-first order stable across native-period/path groups.
    results.sort(key=lambda row: row["observed_at"] or "", reverse=True)
    return results
