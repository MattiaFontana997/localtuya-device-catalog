"""Tests for newer runtime converters used by productless fingerprints."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from import_tuya_local_productless import ConversionError, convert_profile  # noqa: E402


class ProductlessExtendedConverterTests(unittest.TestCase):
    def _convert(self, entities):
        return convert_profile(
            {
                "name": "Test",
                "products": [{"id": "synthetic"}],
                "entities": entities,
            },
            source_file="test.yaml",
        )

    def test_second_only_time_preserves_total_seconds_semantics(self):
        result = self._convert([
            {
                "entity": "time",
                "dps": [
                    {
                        "id": 9,
                        "name": "second",
                        "type": "integer",
                        "range": {"min": 0, "max": 86400},
                    }
                ],
            }
        ])
        config = result["entities"][0]["config"]
        self.assertEqual(config["id"], 9)
        self.assertEqual(config["time_second_dp"], 9)
        self.assertEqual(result["match"]["required_dps"], [9])

    def test_split_time_keeps_all_component_dps(self):
        result = self._convert([
            {
                "entity": "time",
                "dps": [
                    {"id": 1, "name": "hour", "type": "integer"},
                    {"id": 2, "name": "minute", "type": "integer"},
                    {"id": 3, "name": "second", "type": "integer", "optional": True},
                ],
            }
        ])
        config = result["entities"][0]["config"]
        self.assertEqual(config["time_hour_dp"], 1)
        self.assertEqual(config["time_minute_dp"], 2)
        self.assertEqual(config["time_second_dp"], 3)
        self.assertEqual(result["match"]["required_dps"], [1, 2])
        self.assertEqual(result["match"]["optional_dps"], [3])

    def test_time_extra_dp_is_preserved_as_raw_attribute(self):
        result = self._convert([
            {
                "entity": "time",
                "dps": [
                    {"id": 9, "name": "second", "type": "integer"},
                    {"id": 42, "name": "cycle_time", "type": "string"},
                ],
            }
        ])
        config = result["entities"][0]["config"]
        self.assertEqual(config["extra_state_attributes_dps"], {"cycle_time": 42})
        self.assertEqual(result["match"]["required_dps"], [9, 42])

    def test_hms_time_stays_fail_closed(self):
        with self.assertRaisesRegex(ConversionError, "time_hms_not_lossless"):
            self._convert([
                {
                    "entity": "time",
                    "dps": [{"id": 1, "name": "hms", "type": "string"}],
                }
            ])

    def test_static_event_mapping_converts_exact_raw_values(self):
        result = self._convert([
            {
                "entity": "event",
                "dps": [
                    {
                        "id": 14,
                        "name": "event",
                        "type": "string",
                        "mapping": [
                            {"dps_val": "loweralarm", "value": "low"},
                            {"dps_val": "upperalarm", "value": "high"},
                            {"dps_val": "cancel", "value": "normal"},
                        ],
                    }
                ],
            }
        ])
        config = result["entities"][0]["config"]
        self.assertEqual(config["event_dp"], 14)
        self.assertEqual(
            config["event_types"],
            {"low": "loweralarm", "high": "upperalarm", "normal": "cancel"},
        )

    def test_event_default_rule_without_exact_raw_value_is_rejected(self):
        with self.assertRaisesRegex(ConversionError, "event_mapping"):
            self._convert([
                {
                    "entity": "event",
                    "dps": [
                        {
                            "id": 14,
                            "name": "event",
                            "type": "string",
                            "mapping": [{"value": "alarm"}],
                        }
                    ],
                }
            ])


if __name__ == "__main__":
    unittest.main()
