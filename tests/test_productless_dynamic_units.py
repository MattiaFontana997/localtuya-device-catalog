"""Productless live-unit DP importer regressions."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import import_tuya_local as base


class ProductlessDynamicUnitTests(unittest.TestCase):
    def test_sensor_consumes_mapped_unit_dp(self):
        entity = {
            "entity": "sensor", "class": "temperature",
            "dps": [
                {"id": 18, "type": "integer", "name": "sensor", "class": "measurement"},
                {"id": 101, "type": "string", "name": "unit", "mapping": [
                    {"dps_val": "f", "value": "F"}, {"value": "C"}
                ]},
            ],
        }
        converted, required, optional = base._CONVERTERS["sensor"](entity)
        config = converted["config"]
        self.assertEqual(config["dynamic_unit_dp"], 101)
        self.assertEqual(config["advanced_mapping_by_dp"]["101"], [
            {"dps_val": "f", "value": "F"}, {"value": "C"}
        ])
        self.assertEqual(required, {18, 101})
        self.assertEqual(optional, set())
        self.assertNotIn("unit", config.get("extra_state_attributes_dps", {}))

    def test_number_consumes_mapped_unit_dp(self):
        entity = {
            "entity": "number", "class": "temperature_delta",
            "dps": [
                {"id": 27, "type": "integer", "name": "value", "range": {"min": -5, "max": 5}},
                {"id": 23, "type": "string", "name": "unit", "mapping": [
                    {"dps_val": "f", "value": "F"}, {"value": "C"}
                ]},
            ],
        }
        converted, required, optional = base._CONVERTERS["number"](entity)
        self.assertEqual(converted["config"]["dynamic_unit_dp"], 23)
        self.assertEqual(required, {23, 27})
        self.assertEqual(optional, set())

    def test_optional_dynamic_unit_stays_fail_closed(self):
        entity = {
            "entity": "sensor", "class": "temperature",
            "dps": [
                {"id": 1, "type": "integer", "name": "sensor"},
                {"id": 2, "type": "string", "name": "unit", "optional": True,
                 "mapping": [{"value": "C"}]},
            ],
        }
        with self.assertRaisesRegex(base.ConversionError, "multi_dp_mapped_extra:unit"):
            base._CONVERTERS["sensor"](entity)
