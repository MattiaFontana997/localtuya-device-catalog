"""Tests for conservative Tuya Local fan importing."""

import unittest

from tools.import_tuya_local import ConversionError, convert_profile


def profile(dps):
    return {
        "name": "Fan",
        "products": [{"id": "fan-product"}],
        "entities": [{"entity": "fan", "dps": dps}],
    }


class TuyaLocalFanImporterTests(unittest.TestCase):
    def test_integer_speed_and_boolean_oscillation_convert(self):
        mapping = convert_profile(profile([
            {"id": 1, "type": "boolean", "name": "switch"},
            {"id": 3, "type": "integer", "name": "speed", "range": {"min": 1, "max": 3}},
            {"id": 5, "type": "boolean", "name": "oscillate"},
        ]), source_file="powr_curve.yaml")
        config = mapping["entities"][0]["config"]
        self.assertEqual(config["fan_speed_control"], 3)
        self.assertEqual((config["fan_speed_min"], config["fan_speed_max"]), (1, 3))
        self.assertEqual(config["fan_dps_type"], "int")
        self.assertEqual(config["fan_oscillating_control"], 5)
        self.assertNotIn("fan_oscillating_on", config)

    def test_static_presets_preserve_exact_raw_values(self):
        mapping = convert_profile(profile([
            {"id": 1, "type": "boolean", "name": "switch"},
            {"id": 2, "type": "string", "name": "preset_mode", "mapping": [
                {"dps_val": "Normal", "value": "normal"},
                {"dps_val": "Nature", "value": "nature"},
                {"dps_val": "Sleep", "value": "sleep"},
                {"dps_val": "Breeze", "value": "fresh"},
            ]},
            {"id": 3, "type": "integer", "name": "speed", "range": {"min": 1, "max": 5}},
        ]), source_file="aziot.yaml")
        config = mapping["entities"][0]["config"]
        self.assertEqual(config["fan_preset_dp"], 2)
        self.assertEqual(config["fan_preset_values"]["fresh"], "Breeze")

    def test_string_oscillation_mapping_is_lossless(self):
        mapping = convert_profile(profile([
            {"id": 1, "type": "boolean", "name": "switch"},
            {"id": 7, "type": "string", "name": "oscillate", "mapping": [
                {"dps_val": "off", "value": False},
                {"dps_val": "on", "value": True},
            ]},
        ]), source_file="mist.yaml")
        config = mapping["entities"][0]["config"]
        self.assertEqual(config["fan_oscillating_on"], "on")
        self.assertEqual(config["fan_oscillating_off"], "off")

    def test_ordered_string_speed_mapping_converts(self):
        percentages = [8, 17, 25, 33, 42, 50, 58, 67, 75, 83, 92, 100]
        rules = [
            {"dps_val": str(index), "value": percentage}
            for index, percentage in enumerate(percentages, 1)
        ]
        mapping = convert_profile(profile([
            {"id": 1, "type": "boolean", "name": "switch"},
            {"id": 3, "type": "string", "name": "speed", "mapping": rules},
        ]), source_file="arlec.yaml")
        config = mapping["entities"][0]["config"]
        self.assertEqual(config["fan_speed_ordered_list"], ",".join(str(i) for i in range(1, 13)))
        self.assertEqual(config["fan_dps_type"], "str")

    def test_direction_mapping_converts_exact_values(self):
        mapping = convert_profile(profile([
            {"id": 1, "type": "boolean", "name": "switch"},
            {"id": 4, "type": "string", "name": "direction", "mapping": [
                {"dps_val": "F", "value": "forward"},
                {"dps_val": "R", "value": "reverse"},
            ]},
        ]), source_file="direction.yaml")
        config = mapping["entities"][0]["config"]
        self.assertEqual(config["fan_direction_forward"], "F")
        self.assertEqual(config["fan_direction_reverse"], "R")

    def test_non_uniform_speed_percentages_fail_closed(self):
        with self.assertRaisesRegex(ConversionError, "fan_speed_percentages"):
            convert_profile(profile([
                {"id": 1, "type": "boolean", "name": "switch"},
                {"id": 3, "type": "string", "name": "speed", "mapping": [
                    {"dps_val": "low", "value": 10},
                    {"dps_val": "high", "value": 100},
                ]},
            ]), source_file="unsafe.yaml")

    def test_unknown_fan_dp_fails_closed(self):
        with self.assertRaisesRegex(ConversionError, "fan_unsupported_dp:mystery"):
            convert_profile(profile([
                {"id": 1, "type": "boolean", "name": "switch"},
                {"id": 99, "type": "string", "name": "mystery"},
            ]), source_file="unknown.yaml")

    def test_speed_only_fan_stays_fail_closed(self):
        with self.assertRaisesRegex(ConversionError, "fan_missing_switch"):
            convert_profile(profile([
                {"id": 3, "type": "integer", "name": "speed", "range": {"min": 0, "max": 5}},
            ]), source_file="speed_only.yaml")


if __name__ == "__main__":
    unittest.main()
