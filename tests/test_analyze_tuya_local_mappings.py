"""Tests for Tuya Local mapping-rule analysis."""

from __future__ import annotations

import unittest

from tools.analyze_tuya_local_mappings import analyze_profile, build_report


class TuyaLocalMappingAnalysisTests(unittest.TestCase):
    def test_static_mapping_is_detected(self):
        result = analyze_profile(
            {
                "name": "Switch",
                "entities": [
                    {
                        "entity": "switch",
                        "dps": [
                            {
                                "id": 1,
                                "type": "string",
                                "name": "switch",
                                "mapping": [
                                    {"dps_val": "on", "value": True},
                                    {"dps_val": "off", "value": False},
                                ],
                            }
                        ],
                    }
                ],
            }
        )
        self.assertEqual(result.classification, "static_mapping")
        self.assertTrue(result.supported_platforms_only)
        self.assertEqual(result.mapping_dp_count, 1)
        self.assertEqual(result.mapping_rule_count, 2)

    def test_constraint_mapping_is_advanced(self):
        result = analyze_profile(
            {
                "name": "Thermostat",
                "entities": [
                    {
                        "entity": "climate",
                        "dps": [
                            {
                                "id": 2,
                                "type": "integer",
                                "name": "temperature",
                                "mapping": [
                                    {
                                        "constraint": "preset_mode",
                                        "conditions": [
                                            {
                                                "dps_val": "eco",
                                                "value_redirect": "eco_temperature",
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        )
        self.assertEqual(result.classification, "advanced_mapping")
        self.assertIn("constraint", result.advanced_keys)
        self.assertIn("conditions", result.advanced_keys)
        self.assertIn("value_redirect", result.advanced_keys)

    def test_unknown_mapping_key_is_not_silently_accepted(self):
        result = analyze_profile(
            {
                "name": "Future profile",
                "entities": [
                    {
                        "entity": "sensor",
                        "dps": [
                            {
                                "id": 5,
                                "mapping": [
                                    {"dps_val": 1, "future_rule": "x"}
                                ],
                            }
                        ],
                    }
                ],
            }
        )
        self.assertEqual(result.classification, "unknown_semantics")
        self.assertEqual(result.unknown_keys, ("future_rule",))

    def test_report_splits_supported_platforms(self):
        static = analyze_profile(
            {
                "entities": [
                    {
                        "entity": "switch",
                        "dps": [
                            {"id": 1, "mapping": [{"dps_val": 1, "value": True}]}
                        ],
                    }
                ]
            },
            file_name="switch.yaml",
        )
        unsupported = analyze_profile(
            {
                "entities": [
                    {
                        "entity": "lock",
                        "dps": [
                            {"id": 1, "mapping": [{"dps_val": 1, "value": True}]}
                        ],
                    }
                ]
            },
            file_name="lock.yaml",
        )
        report = build_report([static, unsupported])
        self.assertEqual(report["profiles_with_mapping"], 2)
        self.assertEqual(report["supported_platform_profiles_with_mapping"], 1)
        self.assertEqual(
            report["supported_platform_classification_counts"]["static_mapping"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
