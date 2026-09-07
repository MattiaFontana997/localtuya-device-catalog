"""Lossless bitfield and duplicate raw-DP aliases for binary sensors."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import import_tuya_local as base
import import_tuya_local_productless  # noqa: F401


class ProductlessBinarySensorAliasTests(unittest.TestCase):
    def test_advanced_bitfield_sensor_keeps_raw_constraint_and_same_dp_aliases(self):
        entity = {
            "entity": "binary_sensor",
            "class": "problem",
            "dps": [
                {
                    "id": 116, "type": "bitfield", "name": "sensor",
                    "mapping": [
                        {
                            "dps_val": 0, "value": True, "constraint": "fault_code",
                            "conditions": [
                                {"dps_val": 0, "value": False},
                                {"dps_val": 4, "value": False},
                            ],
                        },
                        {"value": True},
                    ],
                },
                {"id": 115, "type": "bitfield", "name": "fault_code"},
                {"id": 116, "type": "bitfield", "name": "fault_code_2"},
            ],
        }
        converted, required, optional = base._CONVERTERS["binary_sensor"](entity)
        config = converted["config"]
        self.assertEqual(config["id"], 116)
        self.assertEqual(config["state_on"], "True")
        self.assertEqual(config["state_off"], "False")
        self.assertNotIn("binary_sensor_mapping", config)
        self.assertEqual(config["advanced_mapping_by_dp"]["116"], [
            {
                "dps_val": 0, "value": True, "bitmask": True,
                "constraint_dp": 115,
                "conditions": [
                    {"dps_val": 0, "value": False, "bitmask": True},
                    {"dps_val": 4, "value": False, "bitmask": True},
                ],
            },
            {"value": True},
        ])
        self.assertEqual(
            config["extra_state_attributes_dps"],
            {"fault_code": 115, "fault_code_2": 116},
        )
        self.assertEqual(required, {115, 116})
        self.assertEqual(optional, set())

    def test_mapped_same_dp_alias_stays_fail_closed(self):
        entity = {
            "entity": "binary_sensor",
            "dps": [
                {
                    "id": 10, "type": "integer", "name": "sensor",
                    "mapping": [
                        {"constraint": "mode", "conditions": [{"dps_val": 0, "value": False}]},
                    ],
                },
                {"id": 11, "type": "integer", "name": "mode"},
                {
                    "id": 10, "type": "integer", "name": "alias",
                    "mapping": [{"dps_val": 1, "value": "one"}],
                },
            ],
        }
        with self.assertRaisesRegex(base.ConversionError, "binary_sensor_duplicate_dp_id"):
            base._CONVERTERS["binary_sensor"](entity)

    def test_duplicate_non_primary_attributes_stay_fail_closed(self):
        entity = {
            "entity": "binary_sensor",
            "dps": [
                {
                    "id": 10, "type": "integer", "name": "sensor",
                    "mapping": [
                        {"constraint": "mode", "conditions": [{"dps_val": 0, "value": False}]},
                    ],
                },
                {"id": 11, "type": "integer", "name": "mode"},
                {"id": 11, "type": "integer", "name": "mode_alias"},
            ],
        }
        with self.assertRaisesRegex(base.ConversionError, "binary_sensor_duplicate_dp_id"):
            base._CONVERTERS["binary_sensor"](entity)

    def test_non_boolean_advanced_binary_sensor_value_stays_fail_closed(self):
        entity = {
            "entity": "binary_sensor",
            "dps": [
                {
                    "id": 10, "type": "bitfield", "name": "sensor",
                    "mapping": [{"dps_val": 1, "value": "bad", "invalid": False}],
                },
            ],
        }
        with self.assertRaisesRegex(base.ConversionError, "advanced_mapping_binary_sensor_value"):
            base._CONVERTERS["binary_sensor"](entity)
