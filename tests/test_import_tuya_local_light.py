"""Tests for lossless Tuya Local light profile conversion."""

from __future__ import annotations

import unittest

from tools.import_tuya_local import ConversionError, convert_profile


class TuyaLocalLightImporterTests(unittest.TestCase):
    def test_onoff_light_converts(self):
        mapping = convert_profile(
            {
                "products": [{"id": "onoff-light"}],
                "entities": [
                    {
                        "entity": "light",
                        "dps": [
                            {"id": 20, "type": "boolean", "name": "switch"}
                        ],
                    }
                ],
            },
            source_file="onoff_light.yaml",
        )

        self.assertEqual(mapping["match"]["required_dps"], [20])
        self.assertEqual(mapping["match"]["optional_dps"], [])
        self.assertEqual(
            mapping["entities"][0]["config"],
            {"id": 20, "platform": "light", "music_mode": False},
        )

    def test_dimmer_cct_light_converts_ranges(self):
        mapping = convert_profile(
            {
                "products": [{"id": "cct-light"}],
                "entities": [
                    {
                        "entity": "light",
                        "dps": [
                            {"id": 20, "type": "boolean", "name": "switch"},
                            {
                                "id": 22,
                                "type": "integer",
                                "name": "brightness",
                                "range": {"min": 5, "max": 1000},
                            },
                            {
                                "id": 23,
                                "type": "integer",
                                "name": "color_temp",
                                "range": {"min": 0, "max": 1000},
                                "mapping": [
                                    {
                                        "target_range": {
                                            "min": 3000,
                                            "max": 6000,
                                        }
                                    }
                                ],
                            },
                        ],
                    }
                ],
            },
            source_file="cct_light.yaml",
        )

        config = mapping["entities"][0]["config"]
        self.assertEqual(config["brightness"], 22)
        self.assertEqual(config["brightness_lower"], 5)
        self.assertEqual(config["brightness_upper"], 1000)
        self.assertEqual(config["color_temp"], 23)
        self.assertEqual(config["color_temp_min_kelvin"], 3000)
        self.assertEqual(config["color_temp_max_kelvin"], 6000)
        self.assertFalse(config["color_temp_reverse"])
        self.assertEqual(mapping["match"]["required_dps"], [20, 22, 23])

    def test_inverted_cct_mapping_sets_reverse(self):
        mapping = convert_profile(
            {
                "products": [{"id": "reverse-cct"}],
                "entities": [
                    {
                        "entity": "light",
                        "dps": [
                            {"id": 1, "type": "boolean", "name": "switch"},
                            {
                                "id": 3,
                                "type": "integer",
                                "name": "color_temp",
                                "range": {"min": 0, "max": 255},
                                "mapping": [
                                    {
                                        "target_range": {
                                            "min": 2700,
                                            "max": 6500,
                                        },
                                        "invert": True,
                                    }
                                ],
                            },
                        ],
                    }
                ],
            },
            source_file="reverse_cct.yaml",
        )

        config = mapping["entities"][0]["config"]
        self.assertEqual(config["brightness_lower"], 0)
        self.assertEqual(config["brightness_upper"], 255)
        self.assertTrue(config["color_temp_reverse"])

    def test_standard_hsv_light_converts(self):
        mapping = convert_profile(
            {
                "products": [{"id": "hsv-light"}],
                "entities": [
                    {
                        "entity": "light",
                        "dps": [
                            {"id": 20, "type": "boolean", "name": "switch"},
                            {
                                "id": 21,
                                "type": "string",
                                "name": "color_mode",
                                "mapping": [
                                    {"dps_val": "colour", "value": "hs"}
                                ],
                            },
                            {
                                "id": 24,
                                "type": "hex",
                                "name": "rgbhsv",
                                "format": [
                                    {
                                        "name": "h",
                                        "bytes": 2,
                                        "range": {"min": 0, "max": 360},
                                    },
                                    {
                                        "name": "s",
                                        "bytes": 2,
                                        "range": {"min": 0, "max": 1000},
                                    },
                                    {
                                        "name": "v",
                                        "bytes": 2,
                                        "range": {"min": 0, "max": 1000},
                                    },
                                ],
                            },
                        ],
                    }
                ],
            },
            source_file="hsv_light.yaml",
        )

        config = mapping["entities"][0]["config"]
        self.assertEqual(config["color_mode"], 21)
        self.assertEqual(config["color"], 24)
        self.assertEqual(config["brightness_lower"], 0)
        self.assertEqual(config["brightness_upper"], 1000)

    def test_optional_light_capability_becomes_optional_dp(self):
        mapping = convert_profile(
            {
                "products": [{"id": "optional-dimmer"}],
                "entities": [
                    {
                        "entity": "light",
                        "dps": [
                            {"id": 20, "type": "boolean", "name": "switch"},
                            {
                                "id": 22,
                                "type": "integer",
                                "name": "brightness",
                                "optional": True,
                                "range": {"min": 10, "max": 1000},
                            },
                        ],
                    }
                ],
            },
            source_file="optional_dimmer.yaml",
        )

        self.assertEqual(mapping["match"]["required_dps"], [20])
        self.assertEqual(mapping["match"]["optional_dps"], [22])

    def test_effect_modes_are_rejected(self):
        with self.assertRaisesRegex(ConversionError, "light_color_mode_effects"):
            convert_profile(
                {
                    "products": [{"id": "scene-light"}],
                    "entities": [
                        {
                            "entity": "light",
                            "dps": [
                                {"id": 20, "type": "boolean", "name": "switch"},
                                {
                                    "id": 21,
                                    "type": "string",
                                    "name": "color_mode",
                                    "mapping": [
                                        {"dps_val": "scene", "value": "Scene"}
                                    ],
                                },
                            ],
                        }
                    ],
                },
                source_file="scene_light.yaml",
            )

    def test_unknown_light_attribute_is_rejected(self):
        with self.assertRaisesRegex(
            ConversionError, "light_unsupported_dp:control_data"
        ):
            convert_profile(
                {
                    "products": [{"id": "extra-light"}],
                    "entities": [
                        {
                            "entity": "light",
                            "dps": [
                                {"id": 20, "type": "boolean", "name": "switch"},
                                {
                                    "id": 28,
                                    "type": "string",
                                    "name": "control_data",
                                    "optional": True,
                                },
                            ],
                        }
                    ],
                },
                source_file="extra_light.yaml",
            )

    def test_rgb_brightness_range_mismatch_is_rejected(self):
        with self.assertRaisesRegex(
            ConversionError, "light_rgbhsv_range_mismatch"
        ):
            convert_profile(
                {
                    "products": [{"id": "rgb-range-mismatch"}],
                    "entities": [
                        {
                            "entity": "light",
                            "dps": [
                                {"id": 20, "type": "boolean", "name": "switch"},
                                {
                                    "id": 22,
                                    "type": "integer",
                                    "name": "brightness",
                                    "range": {"min": 10, "max": 1000},
                                },
                                {
                                    "id": 21,
                                    "type": "string",
                                    "name": "color_mode",
                                    "mapping": [
                                        {"dps_val": "colour", "value": "hs"}
                                    ],
                                },
                                {
                                    "id": 24,
                                    "type": "hex",
                                    "name": "rgbhsv",
                                    "format": [
                                        {
                                            "name": "h",
                                            "bytes": 2,
                                            "range": {"min": 0, "max": 360},
                                        },
                                        {
                                            "name": "s",
                                            "bytes": 2,
                                            "range": {"min": 0, "max": 1000},
                                        },
                                        {
                                            "name": "v",
                                            "bytes": 2,
                                            "range": {"min": 0, "max": 1000},
                                        },
                                    ],
                                },
                            ],
                        }
                    ],
                },
                source_file="rgb_range_mismatch.yaml",
            )


if __name__ == "__main__":
    unittest.main()
