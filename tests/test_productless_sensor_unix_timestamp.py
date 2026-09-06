"""Productless Tuya Local unixtime Sensor regressions."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import import_tuya_local as base
import import_tuya_local_productless as productless


convert_sensor = productless._advanced_wrapper("sensor", base._convert_sensor)


class ProductlessUnixSensorTests(unittest.TestCase):
    def test_timestamp_unixtime_projects_to_explicit_runtime_flag(self):
        entity = {
            "entity": "sensor",
            "name": "Planting date",
            "class": "timestamp",
            "category": "diagnostic",
            "dps": [{"id": 109, "type": "unixtime", "name": "sensor"}],
        }
        converted, required, optional = convert_sensor(entity)
        self.assertEqual(converted["config"]["id"], 109)
        self.assertEqual(converted["config"]["device_class"], "timestamp")
        self.assertIs(converted["config"]["sensor_unix_timestamp"], True)
        self.assertEqual(required, {109})
        self.assertEqual(optional, set())

    def test_unixtime_without_timestamp_class_stays_fail_closed(self):
        entity = {
            "entity": "sensor",
            "dps": [{"id": 109, "type": "unixtime", "name": "sensor"}],
        }
        with self.assertRaisesRegex(base.ConversionError, "sensor_dp_type"):
            convert_sensor(entity)

    def test_transformed_unixtime_stays_fail_closed(self):
        entity = {
            "entity": "sensor",
            "class": "timestamp",
            "dps": [{"id": 109, "type": "unixtime", "name": "sensor", "mapping": [{"scale": 10}]}],
        }
        with self.assertRaisesRegex(base.ConversionError, "sensor_unixtime_semantics"):
            convert_sensor(entity)


if __name__ == "__main__":
    unittest.main()
