#!/usr/bin/env bash
set -euo pipefail

# Live smoke test for examples/import_airnow_hourly.py against an existing
# Docker Compose installation. The test uses one existing PM2.5 sensor only as
# a temporary target, verifies the imported rows, and removes those rows before
# exiting so the installation is left unchanged.

SOURCE_DIR="${SOURCE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
INSTALL_DIR="${INSTALL_DIR:-/opt/compassaq-clean-install}"
OUTPUT_CSV="${OUTPUT_CSV:-/tmp/compassaq-airnow-example.csv}"

python "$SOURCE_DIR/examples/test_import_airnow_hourly.py"

if [[ ! -f "$INSTALL_DIR/docker-compose.yml" ]]; then
  echo "INSTALL_DIR does not point to a CompassAQ Docker Compose installation: $INSTALL_DIR" >&2
  exit 2
fi

cd "$INSTALL_DIR"

SENSOR_ID=$(docker compose exec -T api python - <<'PY'
from sqlalchemy import select
from db import SessionLocal
from models import Parameter, Sensor, Unit

with SessionLocal() as session:
    sensor_id = session.execute(
        select(Sensor.sensor_id)
        .join(Parameter, Parameter.parameter_id == Sensor.parameter_id)
        .join(Unit, Unit.unit_id == Sensor.unit_id)
        .where(Parameter.code.in_(("pm25", "pm2_5", "pm2.5")))
        .where(Unit.code.in_(("ug_m3", "ug/m3", "ugm3")))
        .order_by(Sensor.sensor_id)
        .limit(1)
    ).scalar_one_or_none()
    if sensor_id is not None:
        print(sensor_id)
PY
)

if [[ -z "$SENSOR_ID" ]]; then
  echo "No existing PM2.5 ug/m3 sensor is available for the temporary smoke-test target." >&2
  exit 3
fi

echo "temporary_sensor_id=$SENSOR_ID"
python "$SOURCE_DIR/examples/import_airnow_hourly.py" \
  --sensor-id "$SENSOR_ID" \
  --parameter PM2.5 \
  --hours 2 \
  --lookback-hours 24 \
  --output "$OUTPUT_CSV"

test -s "$OUTPUT_CSV"
head -n 5 "$OUTPUT_CSV"

docker cp "$OUTPUT_CSV" aq_api:/tmp/compassaq-airnow-example.csv

# Import through the same service used by the manual CSV upload route, verify
# the exact sensor/timestamp/value tuples, then delete only those test rows.
docker compose exec -T api python - <<'PY'
import csv
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select
from db import SessionLocal
from models import Measurement
from services.csv_measurement_import import import_measurements_csv_text

path = Path("/tmp/compassaq-airnow-example.csv")
text = path.read_text(encoding="utf-8")
rows = list(csv.DictReader(text.splitlines()))
assert rows, "example produced no CSV rows"

expected = []
for row in rows:
    raw = row["datetime"]
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    expected.append((int(row["internalsensorid"]), datetime.fromisoformat(raw), float(row["value"])))

result = import_measurements_csv_text(text)
print(result)
assert result["success"] is True
assert result["inserted_records"] == len(expected)
assert result["failed_records"] == 0

try:
    with SessionLocal() as session:
        for sensor_id, observed_at, value in expected:
            stored = session.execute(
                select(Measurement.value)
                .where(Measurement.sensor_id == sensor_id)
                .where(Measurement.observed_at == observed_at)
            ).scalar_one()
            assert abs(float(stored) - value) < 1e-9
        print(f"verified_measurements={len(expected)}")
finally:
    with SessionLocal() as session:
        for sensor_id, observed_at, _ in expected:
            session.execute(
                delete(Measurement)
                .where(Measurement.sensor_id == sensor_id)
                .where(Measurement.observed_at == observed_at)
            )
        session.commit()
        print("temporary_measurements=removed")
PY

rm -f "$OUTPUT_CSV"
echo "AIRNOW_MANUAL_IMPORT_SMOKE=PASS"
