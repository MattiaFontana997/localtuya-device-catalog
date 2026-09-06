"""Batch N exact Climate temperature-unit normalization tests."""

import unittest

import import_tuya_local_productless as productless


class ProductlessClimateUnitTests(unittest.TestCase):
    def test_string_raw_units_preserve_raw_values(self):
        entity = {
            "entity": "climate",
            "dps": [{
                "id": 19, "name": "temperature_unit", "type": "string",
                "mapping": [
                    {"dps_val": "c", "value": "C"},
                    {"dps_val": "f", "value": "F"},
                ],
            }],
        }
        normalized = productless._normalize_climate_temperature_unit(entity)
        self.assertEqual(normalized["dps"][0]["mapping"], [
            {"dps_val": "c", "value": "celsius"},
            {"dps_val": "f", "value": "fahrenheit"},
        ])
        self.assertEqual(entity["dps"][0]["mapping"][0]["value"], "C")

    def test_boolean_raw_units_remain_typed(self):
        entity = {
            "entity": "climate",
            "dps": [{
                "id": 107, "name": "temperature_unit", "type": "boolean",
                "mapping": [
                    {"dps_val": False, "value": "C"},
                    {"dps_val": True, "value": "F"},
                ],
            }],
        }
        normalized = productless._normalize_climate_temperature_unit(entity)
        rules = normalized["dps"][0]["mapping"]
        self.assertIs(rules[0]["dps_val"], False)
        self.assertIs(rules[1]["dps_val"], True)
        self.assertEqual([r["value"] for r in rules], ["celsius", "fahrenheit"])

    def test_forward_only_unit_fallback_stays_fail_closed(self):
        entity = {
            "entity": "climate",
            "dps": [{
                "id": 23, "name": "temperature_unit", "type": "string",
                "mapping": [
                    {"dps_val": "f", "value": "F"},
                    {"value": "C"},
                ],
            }],
        }
        with self.assertRaisesRegex(Exception, "climate_temperature_unit_mapping"):
            productless._normalize_climate_temperature_unit(entity)


if __name__ == "__main__":
    unittest.main()
