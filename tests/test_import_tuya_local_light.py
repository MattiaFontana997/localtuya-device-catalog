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
        self.assertNotIn("color_brightness_lower", config)
        self.assertNotIn("color_brightness_upper", config)

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

    def test_bare_scene_mode_requires_scene_data(self):
        with self.assertRaisesRegex(ConversionError, "light_scene_data_required"):
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

    def test_mode_only_scenes_convert_to_scene_values(self):
        mapping = convert_profile(
            {
                "products": [{"id": "mode-scene-light"}],
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
                                    {"dps_val": "scene_1", "value": "Flash scene 1"},
                                    {"dps_val": "scene_2", "value": "Flash scene 2"},
                                ],
                            },
                        ],
                    }
                ],
            },
            source_file="mode_scene_light.yaml",
        )

        config = mapping["entities"][0]["config"]
        self.assertEqual(
            config["scene_values"],
            {
                "Flash scene 1": "scene_1",
                "Flash scene 2": "scene_2",
            },
        )
        self.assertEqual(config["color_mode"], 21)

    def test_simple_music_mode_is_preserved(self):
        mapping = convert_profile(
            {
                "products": [{"id": "music-light"}],
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
                                    {"dps_val": "music", "value": "Music"}
                                ],
                            },
                        ],
                    }
                ],
            },
            source_file="music_light.yaml",
        )

        self.assertTrue(mapping["entities"][0]["config"]["music_mode"])

    def test_simple_work_mode_is_preserved_as_extra_state_attribute(self):
        mapping = convert_profile(
            {
                "products": [{"id": "desk-lamp"}],
                "entities": [
                    {
                        "entity": "light",
                        "dps": [
                            {"id": 1, "type": "boolean", "name": "switch"},
                            {"id": 2, "type": "string", "name": "work_mode"},
                            {
                                "id": 3,
                                "type": "integer",
                                "name": "brightness",
                                "optional": True,
                                "range": {"min": 25, "max": 255},
                            },
                        ],
                    }
                ],
            },
            source_file="desk_lamp.yaml",
        )

        config = mapping["entities"][0]["config"]
        self.assertEqual(
            config["extra_state_attributes_dps"],
            {"work_mode": 2},
        )
        self.assertEqual(mapping["match"]["required_dps"], [1, 2])
        self.assertEqual(mapping["match"]["optional_dps"], [3])

    def test_mapped_work_mode_remains_rejected(self):
        with self.assertRaisesRegex(
            ConversionError, "light_work_mode_mapping"
        ):
            convert_profile(
                {
                    "products": [{"id": "mapped-work-mode"}],
                    "entities": [
                        {
                            "entity": "light",
                            "dps": [
                                {"id": 1, "type": "boolean", "name": "switch"},
                                {
                                    "id": 21,
                                    "type": "string",
                                    "name": "work_mode",
                                    "mapping": [
                                        {"dps_val": "white", "value": "white"}
                                    ],
                                },
                            ],
                        }
                    ],
                },
                source_file="mapped_work_mode.yaml",
            )

    def test_dedicated_effect_mapping_converts_exact_values(self):
        mapping = convert_profile(
            {
                "products": [{"id": "effect-light"}],
                "entities": [
                    {
                        "entity": "light",
                        "dps": [
                            {"id": 1, "type": "boolean", "name": "switch"},
                            {
                                "id": 104,
                                "type": "string",
                                "name": "effect",
                                "optional": True,
                                "mapping": [
                                    {"dps_val": "1", "value": "Combination"},
                                    {"dps_val": "2", "value": "In Wave"},
                                    {"dps_val": "8", "value": "Steady"},
                                ],
                            },
                        ],
                    }
                ],
            },
            source_file="effect_light.yaml",
        )

        config = mapping["entities"][0]["config"]
        self.assertEqual(config["effect"], 104)
        self.assertEqual(
            config["effect_values"],
            {
                "Combination": "1",
                "In Wave": "2",
                "Steady": "8",
            },
        )
        self.assertEqual(mapping["match"]["required_dps"], [1])
        self.assertEqual(mapping["match"]["optional_dps"], [104])

    def test_dedicated_effect_mapping_rejects_non_string_raw_value(self):
        with self.assertRaisesRegex(
            ConversionError, "light_effect_non_string_mapping"
        ):
            convert_profile(
                {
                    "products": [{"id": "bad-effect-light"}],
                    "entities": [
                        {
                            "entity": "light",
                            "dps": [
                                {
                                    "id": 1,
                                    "type": "boolean",
                                    "name": "switch",
                                },
                                {
                                    "id": 2,
                                    "type": "string",
                                    "name": "effect",
                                    "mapping": [
                                        {"dps_val": 1, "value": "Scene"}
                                    ],
                                },
                            ],
                        }
                    ],
                },
                source_file="bad_effect_light.yaml",
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

    def test_rgb_brightness_range_mismatch_uses_independent_color_range(self):
        mapping = convert_profile(
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

        config = mapping["entities"][0]["config"]
        self.assertEqual(config["brightness_lower"], 10)
        self.assertEqual(config["brightness_upper"], 1000)
        self.assertEqual(config["color_brightness_lower"], 0)
        self.assertEqual(config["color_brightness_upper"], 1000)

    def test_scene_select_and_hidden_text_fold_into_light(self):
        mapping = convert_profile(
            {
                "products": [{"id": "scene-data-light"}],
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
                    },
                    {
                        "entity": "text",
                        "translation_key": "scene",
                        "hidden": True,
                        "dps": [
                            {"id": 25, "type": "hex", "name": "value"}
                        ],
                    },
                    {
                        "entity": "select",
                        "translation_key": "scene",
                        "dps": [
                            {
                                "id": 25,
                                "type": "string",
                                "name": "option",
                                "mapping": [
                                    {"dps_val": "0103e8", "value": "Palm"},
                                    {"dps_val": "0403e8", "value": "Rainbow"},
                                ],
                            }
                        ],
                    },
                ],
            },
            source_file="scene_data_light.yaml",
        )

        self.assertEqual(len(mapping["entities"]), 2)
        light = mapping["entities"][0]["config"]
        self.assertEqual(light["scene"], 25)
        self.assertEqual(
            light["scene_values"],
            {"Palm": "0103e8", "Rainbow": "0403e8"},
        )
        self.assertEqual(mapping["entities"][1]["platform"], "select")
        self.assertEqual(mapping["match"]["required_dps"], [20, 21, 25])

    def test_optional_scene_transport_stays_optional(self):
        mapping = convert_profile(
            {
                "products": [{"id": "optional-scene-data"}],
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
                    },
                    {
                        "entity": "text",
                        "translation_key": "scene",
                        "hidden": True,
                        "dps": [
                            {
                                "id": 25,
                                "type": "hex",
                                "name": "value",
                                "optional": True,
                            }
                        ],
                    },
                    {
                        "entity": "select",
                        "translation_key": "scene",
                        "dps": [
                            {
                                "id": 25,
                                "type": "string",
                                "name": "option",
                                "optional": True,
                                "mapping": [
                                    {"dps_val": "0103e8", "value": "Palm"}
                                ],
                            }
                        ],
                    },
                ],
            },
            source_file="optional_scene_data.yaml",
        )

        self.assertEqual(mapping["match"]["optional_dps"], [25])

    def test_scene_context_requires_matching_hidden_transport(self):
        with self.assertRaisesRegex(ConversionError, "light_scene_data_required"):
            convert_profile(
                {
                    "products": [{"id": "mismatched-scene-data"}],
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
                        },
                        {
                            "entity": "text",
                            "translation_key": "scene",
                            "hidden": True,
                            "dps": [
                                {"id": 51, "type": "string", "name": "value"}
                            ],
                        },
                        {
                            "entity": "select",
                            "translation_key": "scene",
                            "dps": [
                                {
                                    "id": 25,
                                    "type": "string",
                                    "name": "option",
                                    "mapping": [
                                        {"dps_val": "0103e8", "value": "Palm"}
                                    ],
                                }
                            ],
                        },
                    ],
                },
                source_file="mismatched_scene_data.yaml",
            )


if __name__ == "__main__":
    unittest.main()
