"""Tests for exact Tuya Local light switch mapping conversion."""

from __future__ import annotations

import unittest

from tools.import_tuya_local import ConversionError, convert_profile


class TuyaLocalLightSwitchValueTests(unittest.TestCase):
    @staticmethod
    def _convert(dp):
        return convert_profile(
            {"products": [{"id": "light"}], "entities": [{"entity": "light", "dps": [dp]}]},
            source_file="light_switch.yaml",
        )["entities"][0]["config"]

    def test_inverted_boolean_mapping_converts(self):
        config = self._convert({
            "id": 102, "type": "boolean", "name": "switch",
            "mapping": [{"dps_val": False, "value": True}, {"dps_val": True, "value": False}],
        })
        self.assertIs(config["light_on_value"], False)
        self.assertIs(config["light_off_value"], True)

    def test_string_mapping_converts_exact_values(self):
        config = self._convert({
            "id": 106, "type": "string", "name": "switch",
            "mapping": [{"dps_val": "normal", "value": True}, {"dps_val": "slient", "value": False}],
        })
        self.assertEqual(config["light_on_value"], "normal")
        self.assertEqual(config["light_off_value"], "slient")

    def test_null_false_boolean_rule_is_read_fallback_only(self):
        config = self._convert({
            "id": 20, "type": "boolean", "name": "switch",
            "mapping": [{"dps_val": None, "value": False}],
        })
        self.assertIs(config["light_null_value"], False)
        self.assertNotIn("light_on_value", config)
        self.assertNotIn("light_off_value", config)

    def test_partial_mapping_stays_fail_closed(self):
        with self.assertRaisesRegex(ConversionError, "light_switch_mapping"):
            self._convert({
                "id": 1, "type": "string", "name": "switch",
                "mapping": [{"dps_val": "on", "value": True}],
            })

    def test_wrong_raw_type_stays_fail_closed(self):
        with self.assertRaisesRegex(ConversionError, "light_switch_mapping"):
            self._convert({
                "id": 1, "type": "boolean", "name": "switch",
                "mapping": [{"dps_val": 0, "value": False}, {"dps_val": 1, "value": True}],
            })

    def test_non_boolean_unmapped_switch_stays_fail_closed(self):
        with self.assertRaisesRegex(ConversionError, "light_switch_non_boolean"):
            self._convert({"id": 1, "type": "string", "name": "switch"})


if __name__ == "__main__":
    unittest.main()
