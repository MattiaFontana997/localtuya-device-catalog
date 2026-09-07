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

    def test_boolean_sensor_unit_mapping_preserves_typed_raw_values(self):
        entity = {
            "entity": "sensor", "class": "temperature",
            "dps": [
                {"id": 120, "type": "integer", "name": "sensor", "class": "measurement"},
                {"id": 103, "type": "boolean", "name": "unit", "mapping": [
                    {"dps_val": False, "value": "F"},
                    {"dps_val": True, "value": "C"},
                ]},
            ],
        }
        converted, required, optional = base._CONVERTERS["sensor"](entity)
        config = converted["config"]
        self.assertEqual(config["dynamic_unit_dp"], 103)
        self.assertEqual(config["advanced_mapping_by_dp"]["103"], [
            {"dps_val": False, "value": "F"},
            {"dps_val": True, "value": "C"},
        ])
        self.assertEqual(required, {103, 120})
        self.assertEqual(optional, set())

    def test_boolean_number_unit_mapping_preserves_typed_raw_values(self):
        entity = {
            "entity": "number", "class": "temperature_delta",
            "dps": [
                {"id": 112, "type": "integer", "name": "value", "range": {"min": -9, "max": 9}},
                {"id": 107, "type": "boolean", "name": "unit", "mapping": [
                    {"dps_val": False, "value": "C"},
                    {"dps_val": True, "value": "F"},
                ]},
            ],
        }
        converted, required, optional = base._CONVERTERS["number"](entity)
        self.assertEqual(converted["config"]["dynamic_unit_dp"], 107)
        self.assertEqual(converted["config"]["advanced_mapping_by_dp"]["107"], [
            {"dps_val": False, "value": "C"},
            {"dps_val": True, "value": "F"},
        ])
        self.assertEqual(required, {107, 112})
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
