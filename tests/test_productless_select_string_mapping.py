"""Lossless string-select mapping normalization regressions."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import import_tuya_local as base
import import_tuya_local_productless as productless


convert_select = productless._advanced_wrapper("select", base._convert_select)


class ProductlessStringSelectMappingTests(unittest.TestCase):
    def test_numeric_yaml_raw_values_follow_tuya_string_semantics(self):
        entity = {
            "entity": "select",
            "name": "Humidifier",
            "dps": [{
                "id": 105,
                "type": "string",
                "name": "option",
                "mapping": [
                    {"dps_val": "close", "value": "off"},
                    {"dps_val": 1, "value": "low"},
                    {"dps_val": 2, "value": "medium"},
                    {"dps_val": 3, "value": "high"},
                    {"dps_val": "auto", "value": "auto"},
                ],
            }],
        }
        converted, required, optional = convert_select(entity)
        self.assertEqual(converted["config"]["options"], "close;1;2;3;auto")
        self.assertEqual(
            converted["config"]["options_friendly"],
            "off;low;medium;high;auto",
        )
        self.assertEqual(required, {105})
        self.assertEqual(optional, set())

    def test_large_integer_raw_token_is_preserved_as_exact_decimal_string(self):
        token = 80000000000000000000000000000000
        entity = {
            "entity": "select",
            "dps": [{
                "id": 25,
                "type": "string",
                "name": "option",
                "mapping": [
                    {"dps_val": token, "value": "Screen - Movie"},
                    {
                        "dps_val": 97000000000000000000000000000000,
                        "value": "Color Scene - Pure",
                    },
                ],
            }],
        }
        converted, _, _ = convert_select(entity)
        self.assertEqual(
            converted["config"]["options"],
            "80000000000000000000000000000000;"
            "97000000000000000000000000000000",
        )

    def test_duplicate_after_string_coercion_stays_fail_closed(self):
        entity = {
            "entity": "select",
            "dps": [{
                "id": 1,
                "type": "string",
                "name": "option",
                "mapping": [
                    {"dps_val": 1, "value": "one"},
                    {"dps_val": "1", "value": "other"},
                ],
            }],
        }
        with self.assertRaisesRegex(base.ConversionError, "select_duplicate_option"):
            convert_select(entity)

    def test_null_and_container_raw_values_are_not_normalized(self):
        for raw in (None, [1]):
            with self.subTest(raw=raw):
                entity = {
                    "entity": "select",
                    "dps": [{
                        "id": 1,
                        "type": "string",
                        "name": "option",
                        "mapping": [{"dps_val": raw, "value": "x"}],
                    }],
                }
                with self.assertRaisesRegex(
                    base.ConversionError,
                    "select_non_string_mapping",
                ):
                    convert_select(entity)


if __name__ == "__main__":
    unittest.main()
