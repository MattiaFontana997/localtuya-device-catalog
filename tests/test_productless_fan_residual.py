"""Residual productless fan converter regressions."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import import_tuya_local as base
import import_tuya_local_productless as productless

convert_fan = productless.base._CONVERTERS["fan"]


class ProductlessFanResidualTests(unittest.TestCase):
    def test_speed_only_fan_is_explicitly_no_switch(self):
        entity = {"entity": "fan", "name": "Supply", "dps": [{
            "id": 102, "type": "string", "name": "speed",
            "mapping": [
                {"dps_val": "0", "value": 10},
                {"dps_val": "1", "value": 20},
                {"dps_val": "9", "value": 100},
            ],
        }]}
        converted, required, optional = convert_fan(entity)
        cfg = converted["config"]
        self.assertIs(cfg["fan_no_switch"], True)
        self.assertEqual(cfg["id"], 102)
        self.assertEqual(cfg["fan_speed_control"], 102)
        self.assertEqual(required, {102})
        self.assertEqual(optional, set())

    def test_hidden_preset_default_is_read_fallback_only(self):
        entity = {"entity": "fan", "dps": [
            {"id": 1, "type": "boolean", "name": "switch"},
            {"id": 3, "type": "string", "name": "preset_mode", "mapping": [
                {"dps_val": "Auto", "value": "auto"},
                {"dps_val": "4", "value": "manual"},
                {"value": "manual", "hidden": True},
            ]},
        ]}
        converted, required, optional = convert_fan(entity)
        cfg = converted["config"]
        self.assertEqual(cfg["fan_preset_values"], {"auto": "Auto", "manual": "4"})
        self.assertEqual(cfg["fan_preset_default"], "manual")
        self.assertEqual(required, {1, 3})
        self.assertEqual(optional, set())

    def test_hidden_exact_preset_stays_fail_closed(self):
        entity = {"entity": "fan", "dps": [
            {"id": 1, "type": "boolean", "name": "switch"},
            {"id": 3, "type": "string", "name": "preset_mode", "mapping": [
                {"dps_val": "Auto", "value": "auto"},
                {"dps_val": "X", "value": "manual", "hidden": True},
            ]},
        ]}
        with self.assertRaisesRegex(base.ConversionError, "fan_preset_mapping"):
            convert_fan(entity)


if __name__ == "__main__":
    unittest.main()
