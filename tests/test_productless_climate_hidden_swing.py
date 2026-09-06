"""Batch N hidden Climate swing forward-fallback tests."""

import unittest

import import_tuya_local_productless as productless


class ProductlessClimateHiddenSwingTests(unittest.TestCase):
    def test_hidden_swing_default_becomes_forward_only_advanced_mapping(self):
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
                    "id": 113, "name": "swing_mode", "type": "string",
                    "mapping": [
                        {"dps_val": "0", "value": "off"},
                        {"dps_val": "1", "value": "on"},
                        {"value": "on", "hidden": True},
                    ],
                },
            ],
        }
        prepared, advanced, membership = productless._prepare_advanced_entity(entity, "climate")
        self.assertIn("113", advanced)
        self.assertEqual(advanced["113"][-1], {"value": "on", "hidden": True})
        swing = next(dp for dp in prepared["dps"] if dp["name"] == "swing_mode")
        self.assertEqual(
            swing["mapping"],
            [{"dps_val": "off", "value": "off"}, {"dps_val": "on", "value": "on"}],
        )
        self.assertIn(113, membership)

    def test_hidden_preset_is_not_broadened_by_swing_tranche(self):
        entity = {
            "entity": "climate",
            "dps": [{
                "id": 5, "name": "preset_mode", "type": "string",
                "mapping": [
                    {"dps_val": "low", "value": "none", "hidden": True},
                    {"dps_val": "high", "value": "boost"},
                ],
            }],
        }
        prepared, advanced, membership = productless._prepare_advanced_entity(entity, "climate")
        self.assertEqual(advanced, {})
        self.assertEqual(membership, set())
        self.assertEqual(prepared, entity)


if __name__ == "__main__":
    unittest.main()
