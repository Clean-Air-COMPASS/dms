#!/usr/bin/env python3
"""Download public AirNow hourly observations and write a CompassAQ import CSV.

This example intentionally uses only the Python standard library. It demonstrates
how to adapt a public data source that CompassAQ does not natively import.

AirNow HourlyData records are pipe-delimited and contain:
    date | time | AQSID | site | GMT offset | parameter | units | value | agency

The resulting CompassAQ CSV contains only the fields required by the current
manual measurement importer:
    internalsensorid,datetime,value

Example:
    python examples/import_airnow_hourly.py \
        --sensor-id 123 \
        --parameter PM2.5 \
        --aqsid 060790800 \
        --hours 6 \
        --output airnow_pm25.csv

The CompassAQ sensor must already exist and must represent the same pollutant,
unit, and aggregation represented by the selected AirNow observations.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


AIRNOW_TODAY_BASE_URL = "https://files.airnowtech.org/airnow/today"
USER_AGENT = "CompassAQ-AirNow-Example/1.0"


@dataclass(frozen=True)
class AirNowObservation:
    valid_at_utc: datetime
    aqsid: str
    site_name: str
    parameter: str
    units: str
    value: float
    agency: str


def _hourly_file_url(valid_hour_utc: datetime) -> str:
    stamp = valid_hour_utc.astimezone(timezone.utc).strftime("%Y%m%d%H")
    return f"{AIRNOW_TODAY_BASE_URL}/HourlyData_{stamp}.dat"


def _download_text(url: str, timeout_seconds: int = 30) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout_seconds) as response:
        payload = response.read()
    # AirNow files have historically contained occasional extended characters.
    # UTF-8 is preferred; cp437 keeps older site names readable when necessary.
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return payload.decode("cp437")


def _parse_gmt_offset(raw_value: str) -> timezone:
    try:
        hours = float(raw_value.strip())
    except ValueError as exc:
        raise ValueError(f"invalid AirNow GMT offset {raw_value!r}") from exc
    return timezone(timedelta(hours=hours))


def parse_hourly_data(text: str) -> list[AirNowObservation]:
    observations: list[AirNowObservation] = []
    reader = csv.reader(io.StringIO(text), delimiter="|")
    for line_number, row in enumerate(reader, start=1):
        if not row or not any(cell.strip() for cell in row):
            continue
        if len(row) < 9:
            raise ValueError(
                f"AirNow row {line_number} has {len(row)} fields; expected at least 9"
            )

        raw_date, raw_time, aqsid, site_name, raw_offset, parameter, units, raw_value, agency = (
            cell.strip() for cell in row[:9]
        )
        try:
            local_naive = datetime.strptime(
                f"{raw_date} {raw_time}", "%m/%d/%y %H:%M"
            )
            local_standard = local_naive.replace(tzinfo=_parse_gmt_offset(raw_offset))
            valid_at_utc = local_standard.astimezone(timezone.utc)
            value = float(raw_value)
        except ValueError as exc:
            raise ValueError(f"invalid AirNow row {line_number}: {exc}") from exc

        observations.append(
            AirNowObservation(
                valid_at_utc=valid_at_utc,
                aqsid=aqsid,
                site_name=site_name,
                parameter=parameter,
                units=units,
                value=value,
                agency=agency,
            )
        )
    return observations


def _matches(value: str, requested: str | None) -> bool:
    return requested is None or value.casefold() == requested.casefold()


def select_observations(
    observations: list[AirNowObservation],
    *,
    parameter: str,
    aqsid: str | None,
) -> list[AirNowObservation]:
    return [
        observation
        for observation in observations
        if _matches(observation.parameter, parameter)
        and _matches(observation.aqsid, aqsid)
    ]


def download_recent_observations(
    *,
    parameter: str,
    aqsid: str | None,
    hours: int,
    lookback_hours: int,
    reference_time_utc: datetime | None = None,
) -> list[AirNowObservation]:
    if hours <= 0:
        raise ValueError("hours must be greater than zero")
    if lookback_hours < hours:
        raise ValueError("lookback-hours must be at least as large as hours")

    reference = (reference_time_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    current_hour = reference.replace(minute=0, second=0, microsecond=0)
    selected: list[AirNowObservation] = []
    selected_instants: set[datetime] = set()
    selected_aqsid = aqsid

    for offset in range(lookback_hours + 1):
        valid_hour = current_hour - timedelta(hours=offset)
        url = _hourly_file_url(valid_hour)
        try:
            text = _download_text(url)
        except HTTPError as exc:
            if exc.code == 404:
                continue
            raise RuntimeError(f"AirNow returned HTTP {exc.code} for {url}") from exc
        except URLError as exc:
            raise RuntimeError(f"Could not download AirNow data from {url}: {exc}") from exc

        matches = select_observations(
            parse_hourly_data(text), parameter=parameter, aqsid=selected_aqsid
        )
        if selected_aqsid is None and matches:
            # Pick one site deterministically and keep that same site for older files.
            selected_aqsid = min(observation.aqsid for observation in matches)
            matches = [
                observation for observation in matches if observation.aqsid == selected_aqsid
            ]

        for observation in sorted(matches, key=lambda item: item.valid_at_utc, reverse=True):
            if observation.valid_at_utc in selected_instants:
                continue
            selected.append(observation)
            selected_instants.add(observation.valid_at_utc)
            if len(selected) >= hours:
                return sorted(selected, key=lambda item: item.valid_at_utc)

    return sorted(selected, key=lambda item: item.valid_at_utc)


def write_compassaq_csv(
    observations: list[AirNowObservation], *, sensor_id: int, output_path: Path
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("internalsensorid", "datetime", "value"))
        for observation in observations:
            writer.writerow(
                (
                    sensor_id,
                    observation.valid_at_utc.isoformat().replace("+00:00", "Z"),
                    format(observation.value, ".12g"),
                )
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Download public AirNow HourlyData observations and convert them to "
            "CompassAQ's manual measurement CSV format."
        )
    )
    parser.add_argument("--sensor-id", type=int, required=True, help="Existing CompassAQ sensor_id")
    parser.add_argument("--parameter", default="PM2.5", help="AirNow parameter name (default: PM2.5)")
    parser.add_argument("--aqsid", help="AirNow AQSID. If omitted, one matching site is chosen deterministically.")
    parser.add_argument("--hours", type=int, default=3, help="Number of hourly observations to output (default: 3)")
    parser.add_argument(
        "--lookback-hours",
        type=int,
        default=24,
        help="Maximum recent hours to search for available AirNow files (default: 24)",
    )
    parser.add_argument("--output", type=Path, default=Path("airnow_compassaq.csv"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        observations = download_recent_observations(
            parameter=args.parameter,
            aqsid=args.aqsid,
            hours=args.hours,
            lookback_hours=args.lookback_hours,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not observations:
        print(
            "No matching AirNow observations were found in the requested lookback window.",
            file=sys.stderr,
        )
        return 2

    write_compassaq_csv(observations, sensor_id=args.sensor_id, output_path=args.output)
    first = observations[0]
    print(f"Wrote {len(observations)} observation(s) to {args.output}")
    print(f"AirNow site: {first.aqsid} — {first.site_name}")
    print(f"Parameter/unit: {first.parameter} / {first.units}")
    print(
        "Before importing, confirm the CompassAQ sensor represents this same "
        "pollutant, unit, and hourly aggregation."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
