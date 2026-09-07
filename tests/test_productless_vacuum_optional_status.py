
"""Productless Vacuum optional raw-status semantics."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import import_tuya_local as base
import import_tuya_local_productless  # noqa: F401


class ProductlessVacuumOptionalStatusTests(unittest.TestCase):
    def test_optional_raw_string_status_is_identity_and_stays_optional(self):
        entity = {
            "entity": "vacuum",
            "dps": [
                {"id": 4, "type": "string", "optional": True, "name": "status"},
                {
                    "id": 3, "type": "string", "optional": True, "name": "command",
                    "mapping": [
                        {"dps_val": "smart", "value": "Auto"},
                        {"dps_val": "manual", "value": "Manual"},
                    ],
                },
                {"id": 26, "type": "bitfield", "optional": True, "name": "error"},
                {
                    "id": 8, "type": "string", "optional": True, "name": "fan_speed",
                    "mapping": [
                        {"dps_val": "gentle", "value": "low"},
                        {"dps_val": "normal", "value": "medium"},
                        {"dps_val": "strong", "value": "high"},
                    ],
                },
            ],
        }
        converted, required, optional = base._CONVERTERS["vacuum"](entity)
        config = converted["config"]
        self.assertEqual(config["id"], 4)
        self.assertEqual(config["vacuum_status_dp"], 4)
        self.assertEqual(config["vacuum_status_values"], {})
        self.assertEqual(config["vacuum_command_values"], {"Auto": "smart", "Manual": "manual"})
        self.assertEqual(config["vacuum_fan_speed_values"], {"low": "gentle", "medium": "normal", "high": "strong"})
        self.assertEqual(config["fault_dp"], 26)
        self.assertEqual(required, set())
        self.assertEqual(optional, {3, 4, 8, 26})

    def test_optional_non_string_status_stays_fail_closed(self):
        entity = {
            "entity": "vacuum",
            "dps": [{"id": 4, "type": "integer", "optional": True, "name": "status"}],
        }
        with self.assertRaisesRegex(base.ConversionError, "vacuum_optional_status"):
            base._CONVERTERS["vacuum"](entity)

    def test_required_unmapped_status_stays_fail_closed(self):
        entity = {
            "entity": "vacuum",
            "dps": [{"id": 4, "type": "string", "name": "status"}],
        }
        with self.assertRaisesRegex(base.ConversionError, "vacuum_status_mapping"):
            base._CONVERTERS["vacuum"](entity)
