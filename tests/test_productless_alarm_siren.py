"""Productless Alarm Control Panel and Siren regressions."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import import_tuya_local as base
import import_tuya_local_productless as productless


class ProductlessAlarmSirenTests(unittest.TestCase):
    def test_alarm_state_and_optional_extra(self):
        entity = {
            "entity": "alarm_control_panel",
            "dps": [
                {"id": 1, "type": "string", "name": "alarm_state", "mapping": [
                    {"dps_val": "disarmed", "value": "disarmed"},
                    {"dps_val": "arm", "value": "armed_away"},
                    {"dps_val": "home", "value": "armed_home"},
                    {"dps_val": "sos", "value": "triggered"},
                ]},
                {"id": 24, "type": "string", "name": "zone_attribute", "optional": True},
            ],
        }
        converted, required, optional = productless.base._CONVERTERS["alarm_control_panel"](entity)
        cfg = converted["config"]
        self.assertEqual(cfg["alarm_state_values"]["armed_away"], "arm")
        self.assertEqual(cfg["alarm_state_values"]["triggered"], "sos")
        self.assertEqual(cfg["extra_state_attributes_dps"]["zone_attribute"], 24)
        self.assertEqual(required, {1})
        self.assertEqual(optional, {24})

    def test_siren_tone_volume_duration(self):
        entity = {
            "entity": "siren",
            "dps": [
                {"id": 1, "name": "tone", "type": "string", "mapping": [
                    {"dps_val": "alarm_sound", "value": "sound"},
                    {"dps_val": "alarm_sound_light", "value": "sound+light", "default": True},
                    {"dps_val": "normal", "value": "off"},
                ]},
                {"id": 5, "name": "volume_level", "type": "string", "mapping": [
                    {"dps_val": "mute", "value": 0.0},
                    {"dps_val": "high", "value": 1.0},
                ]},
                {"id": 7, "name": "duration", "type": "integer", "range": {"min": 1, "max": 59}, "unit": "min"},
            ],
        }
        converted, required, optional = productless.base._CONVERTERS["siren"](entity)
        cfg = converted["config"]
        self.assertEqual(cfg["siren_default_tone"], "sound+light")
        self.assertEqual(cfg["siren_tone_values"]["off"], "normal")
        self.assertEqual(cfg["siren_volume_values"]["1.0"], "high")
        self.assertEqual(cfg["siren_duration_scaling"], 1.0)
        self.assertEqual(required, {1, 5, 7})
        self.assertEqual(optional, set())

    def test_alarm_unknown_friendly_fails_closed(self):
        entity = {"entity": "alarm_control_panel", "dps": [{"id": 1, "type": "string", "name": "alarm_state", "mapping": [{"dps_val": "x", "value": "mystery"}]}]}
        with self.assertRaisesRegex(base.ConversionError, "alarm_state_mapping"):
            productless.base._CONVERTERS["alarm_control_panel"](entity)


if __name__ == "__main__":
    unittest.main()
