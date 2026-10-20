from __future__ import annotations

from sqlalchemy import select

import models


def ensure_catalog(session):
    units: dict[str, models.Unit] = {}
    for code, symbol, name in (
        ("ug_m3", "µg/m³", "Micrograms per cubic meter"),
        ("mg_m3", "mg/m³", "Milligrams per cubic meter"),
        ("ppm", "ppm", "Parts per million"),
        ("ppb", "ppb", "Parts per billion"),
        ("celsius", "°C", "Degrees Celsius"),
        ("hpa", "hPa", "Hectopascal"),
        ("percent", "%", "Percent"),
        ("index", "index", "Unitless index"),
    ):
        unit = session.scalar(select(models.Unit).where(models.Unit.code == code))
        if unit is None:
            unit = models.Unit(code=code, symbol=symbol, name=name)
            session.add(unit)
            session.flush()
        units[code] = unit

    parameters: dict[str, models.Parameter] = {}
    for code, display_name, unit_code in (
        ("pm25", "PM2.5", "ug_m3"),
        ("pm10", "PM10", "ug_m3"),
        ("pm1", "PM1", "ug_m3"),
        ("o3", "Ozone", "ppm"),
        ("co2", "CO₂", "ppm"),
        ("temperature", "Temperature", "celsius"),
        ("relative_humidity", "Relative humidity", "percent"),
        ("pressure", "Pressure", "hpa"),
        ("tvoc", "TVOC", "ppb"),
        ("tvoc_index", "VOC Index", "index"),
        ("nox_index", "NOx Index", "index"),
    ):
        parameter = session.scalar(
            select(models.Parameter).where(models.Parameter.code == code)
        )
        if parameter is None:
            parameter = models.Parameter(
                code=code,
                display_name=display_name,
                default_unit_id=units[unit_code].unit_id,
            )
            session.add(parameter)
            session.flush()
        parameters[code] = parameter

    supported_unit_codes = {
        "pm25": ("ug_m3", "mg_m3"),
        "pm10": ("ug_m3", "mg_m3"),
        "o3": ("ppm", "ppb", "ug_m3"),
        "pm1": ("ug_m3",),
        "co2": ("ppm",),
        "temperature": ("celsius",),
        "relative_humidity": ("percent",),
        "pressure": ("hpa",),
        "tvoc": ("ppb",),
        "tvoc_index": ("index",),
        "nox_index": ("index",),
    }
    existing_supported_units = {
        (row.parameter_id, row.unit_id)
        for row in session.scalars(select(models.ParameterSupportedUnit)).all()
    }
    for parameter_code, unit_codes in supported_unit_codes.items():
        for unit_code in unit_codes:
            key = (parameters[parameter_code].parameter_id, units[unit_code].unit_id)
            if key not in existing_supported_units:
                session.add(
                    models.ParameterSupportedUnit(
                        parameter_id=key[0],
                        unit_id=key[1],
                    )
                )
                existing_supported_units.add(key)

    # Older acceptance cases use this dictionary key as a local convenience;
    # the persisted Parameter row remains the one canonical identity.
    parameters["rh"] = parameters["relative_humidity"]

    periods: dict[str, models.AggregationPeriod] = {}
    for code, display_name, minutes in (
        ("2m", "2 Minutes", 2),
        ("1h", "1 Hour", 60),
    ):
        period = session.scalar(
            select(models.AggregationPeriod).where(
                models.AggregationPeriod.code == code
            )
        )
        if period is None:
            period = models.AggregationPeriod(
                code=code,
                display_name=display_name,
                duration_minutes=minutes,
                is_rolling=False,
                expected_interval=f"{minutes // 60:02d}:{minutes % 60:02d}:00",
            )
            session.add(period)
            session.flush()
        periods[code] = period
    session.commit()
    return units, parameters, periods


def ensure_source(session, provider_code: str, name: str) -> models.ExternalAPI:
    source = session.scalar(
        select(models.ExternalAPI).where(
            models.ExternalAPI.provider_code == provider_code
        )
    )
    if source is None:
        source = models.ExternalAPI(
            provider_code=provider_code,
            name=name,
            params={},
        )
        session.add(source)
        session.flush()
    source.name = name
    source.enabled = True
    source.api_key = "acceptance-key"
    return source


def measurement_qc_rows(
    session, measurement_id: int
) -> list[models.MeasurementQCResult]:
    return list(
        session.scalars(
            select(models.MeasurementQCResult)
            .where(models.MeasurementQCResult.measurement_id == measurement_id)
            .order_by(models.MeasurementQCResult.check_code)
        )
    )
