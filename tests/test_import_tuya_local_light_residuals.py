"""Regression tests for residual Tuya Local light encodings."""

from __future__ import annotations

import unittest

from tools.import_tuya_local import ConversionError, convert_profile


class ResidualLightImporterTests(unittest.TestCase):
    @staticmethod
    def _convert(dps):
        result = convert_profile(
            {"products": [{"id": "light"}], "entities": [{"entity": "light", "dps": dps}]},
            source_file="light.yaml",
        )
        return result["entities"][0]["config"]

    def test_masked_hex_switch_converts_exact_mask(self):
        config = self._convert([{
            "id": 123, "name": "switch", "type": "hex", "mask": "0008"
        }])
        self.assertEqual(config["id"], 123)
        self.assertEqual(config["light_power_mask"], "0008")

    def test_brightness_only_power_mapping_converts(self):
        config = self._convert([{
            "id": 101, "name": "brightness", "type": "string",
            "mapping": [
                {"dps_val": "level0", "value": 0},
                {"dps_val": "level1", "value": 85},
                {"dps_val": "level2", "value": 170},
                {"dps_val": "level3", "value": 255},
            ],
        }])
        self.assertTrue(config["brightness_as_power"])
        self.assertEqual(config["id"], 101)
        self.assertEqual(config["brightness"], 101)
        self.assertEqual(config["brightness_values"], {
            "0": "level0", "85": "level1", "170": "level2", "255": "level3"
        })

    def test_brightness_only_requires_off_and_full_on(self):
        with self.assertRaisesRegex(ConversionError, "light_brightness_power_mapping"):
            self._convert([{
                "id": 101, "name": "brightness", "type": "string",
                "mapping": [{"dps_val": "off", "value": 0}, {"dps_val": "mid", "value": 128}],
            }])

    def test_discrete_color_temperature_converts(self):
        config = self._convert([
            {"id": 20, "name": "switch", "type": "boolean"},
            {"id": 22, "name": "brightness", "type": "integer", "range": {"min": 10, "max": 100}},
            {
                "id": 23, "name": "color_temp", "type": "integer", "range": {"min": 1, "max": 3},
                "mapping": [
                    {"dps_val": 1, "value": 3000},
                    {"dps_val": 2, "value": 4000},
                    {"dps_val": 3, "value": 6000},
                    {"target_range": {"min": 3000, "max": 6000}},
                ],
            },
        ])
        self.assertEqual(config["color_temp_values"], {"3000": 1, "4000": 2, "6000": 3})
        self.assertEqual(config["color_temp_min_kelvin"], 3000)
        self.assertEqual(config["color_temp_max_kelvin"], 6000)

    def test_color_temperature_step_converts(self):
        config = self._convert([
            {"id": 9, "name": "switch", "type": "boolean"},
            {"id": 10, "name": "brightness", "type": "integer", "range": {"min": 0, "max": 100}, "mapping": [{"step": 2}]},
            {
                "id": 11, "name": "color_temp", "type": "integer", "range": {"min": 0, "max": 100},
                "mapping": [{"step": 2, "invert": True, "target_range": {"min": 2700, "max": 6500}}],
            },
        ])
        self.assertEqual(config["color_temp_step"], 2)
        self.assertTrue(config["color_temp_reverse"])

    def test_extended_rgbhsv_100_scales_are_preserved(self):
        config = self._convert([
            {"id": 27, "name": "switch", "type": "boolean"},
            {"id": 29, "name": "brightness", "type": "integer", "range": {"min": 25, "max": 255}},
            {
                "id": 31, "name": "rgbhsv", "type": "hex",
                "format": [
                    {"name": "r", "bytes": 1}, {"name": "g", "bytes": 1}, {"name": "b", "bytes": 1},
                    {"name": "h", "bytes": 2, "range": {"min": 0, "max": 360}},
                    {"name": "s", "bytes": 1, "range": {"min": 0, "max": 100}},
                    {"name": "v", "bytes": 1, "range": {"min": 0, "max": 100}},
                ],
            },
        ])
        self.assertTrue(config["color_rgb_encoding"])
        self.assertEqual(config["color_saturation_upper"], 100)
        self.assertEqual(config["color_brightness_lower"], 0)
        self.assertEqual(config["color_brightness_upper"], 100)

    def test_legacy_rgbhsv_saturation_100_converts(self):
        config = self._convert([
            {"id": 2, "name": "switch", "type": "boolean"},
            {
                "id": 11, "name": "rgbhsv", "type": "hex",
                "format": [
                    {"name": "h", "bytes": 2, "range": {"min": 0, "max": 360}},
                    {"name": "s", "bytes": 2, "range": {"min": 0, "max": 100}},
                    {"name": "v", "bytes": 2, "range": {"min": 0, "max": 1000}},
                ],
            },
        ])
        self.assertEqual(config["color_saturation_upper"], 100)
        self.assertEqual(config["brightness_lower"], 0)
        self.assertEqual(config["brightness_upper"], 1000)


if __name__ == "__main__":
    unittest.main()
