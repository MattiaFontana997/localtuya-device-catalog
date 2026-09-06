"""Batch N Climate HVAC action many-to-one mapping tests."""

import unittest

import import_tuya_local_productless as productless


class ProductlessClimateHvacActionTests(unittest.TestCase):
    def test_explicit_many_to_one_action_uses_advanced_mapping(self):
        entity = {
            "entity": "climate",
            "dps": [
                {
                    "id": 1, "name": "hvac_mode", "type": "boolean",
                    "mapping": [
                        {"dps_val": False, "value": "off"},
                        {"dps_val": True, "value": "heat"},
                    ],
                },
                {
                    "id": 104, "name": "hvac_action", "type": "string", "readonly": True,
                    "mapping": [
                        {"dps_val": "heating", "value": "heating"},
                        {"dps_val": "warm", "value": "heating"},
                        {"dps_val": "stop", "value": "idle"},
                        {"dps_val": "standby", "value": "idle"},
                    ],
                },
            ],
        }
        prepared, advanced, membership = productless._prepare_advanced_entity(entity, "climate")
        self.assertEqual(
            advanced["104"],
            [
                {"dps_val": "heating", "value": "heating"},
                {"dps_val": "warm", "value": "heating"},
                {"dps_val": "stop", "value": "idle"},
                {"dps_val": "standby", "value": "idle"},
            ],
        )
        action = next(dp for dp in prepared["dps"] if dp["name"] == "hvac_action")
        self.assertEqual(
            action["mapping"],
            [
                {"dps_val": "heating", "value": "heating"},
                {"dps_val": "idle", "value": "idle"},
            ],
        )
        self.assertIn(104, membership)

    def test_null_fallback_action_remains_fail_closed(self):
        entity = {
            "entity": "climate",
            "dps": [{
                "id": 7, "name": "hvac_action", "type": "boolean", "readonly": True,
                "mapping": [
                    {"dps_val": False, "value": "idle"},
                    {"dps_val": True, "value": "heating"},
                    {"dps_val": None, "value": "idle"},
                ],
            }],
        }
        prepared, advanced, membership = productless._prepare_advanced_entity(entity, "climate")
        self.assertEqual(advanced, {})
        self.assertEqual(membership, set())
        self.assertEqual(prepared, entity)


if __name__ == "__main__":
    unittest.main()
