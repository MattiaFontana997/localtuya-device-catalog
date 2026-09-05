"""Tests for the Tuya Local compatibility analyzer."""

from __future__ import annotations

import unittest

from tools.analyze_tuya_local import analyze_profile, build_report


class TuyaLocalAnalyzerTests(unittest.TestCase):
    def test_simple_switch_is_convertible_v1(self):
        result = analyze_profile(
            {
                "name": "Simple switch",
                "products": [{"id": "product123"}],
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
                    }
                ],
            },
            file_name="simple_switch.yaml",
        )

        self.assertEqual(result.status, "convertible_v1")
        self.assertEqual(result.product_ids, ("product123",))
        self.assertEqual(result.platforms, ("switch",))
        self.assertEqual(result.dp_count, 1)
        self.assertEqual(result.reasons, ())

    def test_optional_dp_requires_schema_v2(self):
        result = analyze_profile(
            {
                "name": "Switch with optional diagnostic",
                "products": [{"id": "product123"}],
                "entities": [
                    {
                        "entity": "switch",
                        "dps": [
                            {
                                "id": 1,
                                "type": "boolean",
                                "name": "switch",
                            },
                            {
                                "id": 2,
                                "type": "integer",
                                "name": "diagnostic",
                                "optional": True,
                            },
                        ],
                    }
                ],
            }
        )

        self.assertEqual(result.status, "needs_v2")
        self.assertIn("v2_feature:optional", result.reasons)

    def test_default_optional_false_does_not_block_v1(self):
        result = analyze_profile(
            {
                "name": "Explicit defaults",
                "products": [{"id": "product123"}],
                "entities": [
                    {
                        "entity": "sensor",
                        "dps": [
                            {
                                "id": 1,
                                "type": "integer",
                                "optional": False,
                                "force": False,
                                "persist": True,
                            }
                        ],
                    }
                ],
            }
        )

        self.assertEqual(result.status, "convertible_v1")

    def test_multiple_product_ids_requires_schema_v2(self):
        result = analyze_profile(
            {
                "name": "Rebranded plug",
                "products": [
                    {"id": "product-a"},
                    {"id": "product-b"},
                ],
                "entities": [
                    {
                        "entity": "switch",
                        "dps": [{"id": 1, "type": "boolean"}],
                    }
                ],
            }
        )

        self.assertEqual(result.status, "needs_v2")
        self.assertIn("multiple_product_ids", result.reasons)

    def test_unsupported_platform_is_reported(self):
        result = analyze_profile(
            {
                "name": "Alarm",
                "products": [{"id": "alarm123"}],
                "entities": [
                    {
                        "entity": "alarm_control_panel",
                        "dps": [{"id": 1, "type": "string"}],
                    }
                ],
            }
        )

        self.assertEqual(result.status, "unsupported_platform")
        self.assertIn(
            "unsupported_platform:alarm_control_panel",
            result.reasons,
        )

    def test_complex_dp_type_requires_schema_v2(self):
        result = analyze_profile(
            {
                "name": "Encoded sensor",
                "products": [{"id": "encoded123"}],
                "entities": [
                    {
                        "entity": "sensor",
                        "dps": [{"id": 10, "type": "base64"}],
                    }
                ],
            }
        )

        self.assertEqual(result.status, "needs_v2")
        self.assertIn("complex_dp_type:base64", result.reasons)

    def test_missing_product_id_is_invalid(self):
        result = analyze_profile(
            {
                "name": "Unknown product",
                "entities": [
                    {
                        "entity": "switch",
                        "dps": [{"id": 1, "type": "boolean"}],
                    }
                ],
            }
        )

        self.assertEqual(result.status, "invalid")
        self.assertIn("missing_product_id", result.reasons)

    def test_report_aggregates_status_and_reasons(self):
        convertible = analyze_profile(
            {
                "products": [{"id": "one"}],
                "entities": [
                    {
                        "entity": "switch",
                        "dps": [{"id": 1, "type": "boolean"}],
                    }
                ],
            },
            file_name="one.yaml",
        )
        needs_v2 = analyze_profile(
            {
                "products": [{"id": "two"}],
                "entities": [
                    {
                        "entity": "sensor",
                        "dps": [
                            {
                                "id": 2,
                                "type": "integer",
                                "force": True,
                            }
                        ],
                    }
                ],
            },
            file_name="two.yaml",
        )

        report = build_report([convertible, needs_v2])

        self.assertEqual(report["profiles"], 2)
        self.assertEqual(report["status_counts"]["convertible_v1"], 1)
        self.assertEqual(report["status_counts"]["needs_v2"], 1)
        self.assertEqual(report["reason_counts"]["v2_feature:force"], 1)
        self.assertEqual(report["platform_counts"]["sensor"], 1)
        self.assertEqual(report["platform_counts"]["switch"], 1)


if __name__ == "__main__":
    unittest.main()
