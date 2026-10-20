from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("import_airnow_hourly.py")
SPEC = importlib.util.spec_from_file_location("import_airnow_hourly", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


SAMPLE = "\n".join(
    [
        "08/27/26|12:00|060790800|Example Site|-8|PM2.5|UG/M3|12.3|Example Agency",
        "08/27/26|12:00|060790800|Example Site|-8|OZONE|PPB|41|Example Agency",
        "08/27/26|13:00|060790801|Other Site|-8|PM2.5|UG/M3|7.5|Other Agency",
    ]
)


class AirNowExampleTests(unittest.TestCase):
    def test_parse_hourly_data_converts_local_standard_time_to_utc(self):
        observations = module.parse_hourly_data(SAMPLE)
        self.assertEqual(len(observations), 3)
        self.assertEqual(observations[0].aqsid, "060790800")
        self.assertEqual(observations[0].parameter, "PM2.5")
        self.assertEqual(observations[0].units, "UG/M3")
        self.assertEqual(observations[0].value, 12.3)
        self.assertEqual(
            observations[0].valid_at_utc,
            datetime(2026, 8, 27, 20, 0, tzinfo=timezone.utc),
        )

    def test_select_observations_filters_parameter_and_site(self):
        observations = module.parse_hourly_data(SAMPLE)
        selected = module.select_observations(
            observations, parameter="pm2.5", aqsid="060790800"
        )
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].value, 12.3)

    def test_write_compassaq_csv_uses_required_columns_and_utc_timestamp(self):
        observation = module.parse_hourly_data(SAMPLE)[0]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out.csv"
            module.write_compassaq_csv([observation], sensor_id=321, output_path=output)
            with output.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(
            rows,
            [
                {
                    "internalsensorid": "321",
                    "datetime": "2026-08-27T20:00:00Z",
                    "value": "12.3",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
