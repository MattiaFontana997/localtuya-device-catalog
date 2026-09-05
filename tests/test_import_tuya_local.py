"""Tests for the conservative Tuya Local -> Catalog V2 importer."""

from __future__ import annotations

import unittest

from tools.import_tuya_local import ConversionError, convert_profile


class TuyaLocalImporterTests(unittest.TestCase):
    def test_select_mapping_converts_to_raw_and_friendly_options(self):
        mapping = convert_profile(
            {
                "name": "Mode selector",
                "products": [{"id": "product-b"}, {"id": "product-a"}],
                "entities": [
                    {
                        "entity": "select",
                        "dps": [
                            {
                                "id": 2,
                                "type": "string",
                                "name": "option",
                                "mapping": [
                                    {"dps_val": "auto", "value": "Automatic"},
                                    {"dps_val": "man", "value": "Manual"},
                                ],
                            }
                        ],
                    }
                ],
            },
            source_file="mode.yaml",
            revision="abc123",
        )

        self.assertEqual(
            mapping["match"]["product_ids"],
            ["product-a", "product-b"],
        )
        self.assertEqual(mapping["match"]["required_dps"], [2])
        config = mapping["entities"][0]["config"]
        self.assertEqual(config["options"], "auto;man")
        self.assertEqual(config["options_friendly"], "Automatic;Manual")
        self.assertEqual(mapping["provenance"]["revision"], "abc123")
        self.assertEqual(mapping["confidence"], "experimental")

    def test_binary_sensor_mapping_preserves_raw_states(self):
        mapping = convert_profile(
            {
                "products": [{"id": "door-product"}],
                "entities": [
                    {
                        "entity": "binary_sensor",
                        "class": "door",
                        "dps": [
                            {
                                "id": 1,
                                "type": "string",
                                "name": "sensor",
                                "mapping": [
                                    {"dps_val": "open", "value": True},
                                    {"dps_val": "closed", "value": False},
                                ],
                            }
                        ],
                    }
                ],
            },
            source_file="door.yaml",
        )

        config = mapping["entities"][0]["config"]
        self.assertEqual(config["state_on"], "open")
        self.assertEqual(config["state_off"], "closed")
        self.assertEqual(config["device_class"], "door")

    def test_sensor_scale_is_inverted_for_localtuya_multiplier(self):
        mapping = convert_profile(
            {
                "products": [{"id": "temperature-product"}],
                "entities": [
                    {
                        "entity": "sensor",
                        "class": "temperature",
                        "dps": [
                            {
                                "id": 24,
                                "type": "integer",
                                "name": "sensor",
                                "unit": "°C",
                                "class": "measurement",
                                "mapping": [{"scale": 10}],
                            }
                        ],
                    }
                ],
            },
            source_file="temperature.yaml",
        )

        config = mapping["entities"][0]["config"]
        self.assertEqual(config["scaling"], 0.1)
        self.assertEqual(config["unit_of_measurement"], "°C")
        self.assertEqual(config["device_class"], "temperature")
        self.assertEqual(config["state_class"], "measurement")

    def test_number_range_step_and_scale_convert_to_native_units(self):
        mapping = convert_profile(
            {
                "products": [{"id": "setpoint-product"}],
                "entities": [
                    {
                        "entity": "number",
                        "dps": [
                            {
                                "id": 16,
                                "type": "integer",
                                "name": "value",
                                "unit": "°C",
                                "range": {"min": 50, "max": 350},
                                "step": 5,
                                "mapping": [{"scale": 10}],
                            }
                        ],
                    }
                ],
            },
            source_file="setpoint.yaml",
        )

        config = mapping["entities"][0]["config"]
        self.assertEqual(config["scaling"], 0.1)
        self.assertEqual(config["min_value"], 5.0)
        self.assertEqual(config["max_value"], 35.0)
        self.assertEqual(config["step_size"], 0.5)

    def test_optional_dp_is_not_a_required_fingerprint_anchor(self):
        mapping = convert_profile(
            {
                "products": [{"id": "optional-product"}],
                "entities": [
                    {
                        "entity": "switch",
                        "dps": [
                            {
                                "id": 1,
                                "type": "boolean",
                                "name": "switch",
                            }
                        ],
                    },
                    {
                        "entity": "sensor",
                        "dps": [
                            {
                                "id": 18,
                                "type": "integer",
                                "name": "sensor",
                                "optional": True,
                            }
                        ],
                    },
                ],
            },
            source_file="optional.yaml",
        )

        self.assertEqual(mapping["match"]["required_dps"], [1])
        self.assertEqual(mapping["match"]["optional_dps"], [18])

    def test_advanced_cross_dp_mapping_is_rejected(self):
        with self.assertRaisesRegex(ConversionError, "advanced_mapping"):
            convert_profile(
                {
                    "products": [{"id": "thermostat"}],
                    "entities": [
                        {
                            "entity": "number",
                            "dps": [
                                {
                                    "id": 16,
                                    "type": "integer",
                                    "name": "value",
                                    "range": {"min": 5, "max": 35},
                                    "mapping": [
                                        {
                                            "constraint": "unit",
                                            "conditions": [
                                                {
                                                    "dps_val": "f",
                                                    "value_redirect": "temp_f",
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
                source_file="thermostat.yaml",
            )

    def test_multi_dp_entity_is_rejected_instead_of_losing_attributes(self):
        with self.assertRaisesRegex(ConversionError, "multi_dp_entity"):
            convert_profile(
                {
                    "products": [{"id": "meter"}],
                    "entities": [
                        {
                            "entity": "sensor",
                            "dps": [
                                {"id": 18, "type": "integer", "name": "sensor"},
                                {"id": 19, "type": "integer", "name": "extra"},
                            ],
                        }
                    ],
                },
                source_file="meter.yaml",
            )

    def test_profile_with_unsupported_entity_is_rejected_atomically(self):
        with self.assertRaisesRegex(ConversionError, "unsupported_platform:light"):
            convert_profile(
                {
                    "products": [{"id": "mixed"}],
                    "entities": [
                        {
                            "entity": "switch",
                            "dps": [
                                {"id": 1, "type": "boolean", "name": "switch"}
                            ],
                        },
                        {
                            "entity": "light",
                            "dps": [
                                {"id": 20, "type": "boolean", "name": "switch"}
                            ],
                        },
                    ],
                },
                source_file="mixed.yaml",
            )

    def test_mapping_id_is_deterministic(self):
        profile = {
            "products": [{"id": "stable-product"}],
            "entities": [
                {
                    "entity": "switch",
                    "dps": [
                        {"id": 1, "type": "boolean", "name": "switch"}
                    ],
                }
            ],
        }

        first = convert_profile(profile, source_file="stable.yaml")
        second = convert_profile(profile, source_file="stable.yaml")
        self.assertEqual(first["id"], second["id"])


if __name__ == "__main__":
    unittest.main()
