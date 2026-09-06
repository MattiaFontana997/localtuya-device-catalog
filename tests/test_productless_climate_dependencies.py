"""Batch N Climate internal advanced dependency tests."""

import unittest

import import_tuya_local_productless as productless


class ProductlessClimateDependencyTests(unittest.TestCase):
    def test_redirect_shadow_dp_is_internal_but_kept_in_membership(self):
        entity = {
            "entity": "climate",
            "dps": [
                {"id": 1, "name": "hvac_mode", "type": "boolean",
                 "mapping": [{"dps_val": False, "value": "off"}, {"dps_val": True, "value": "heat"}]},
                {"id": 2, "name": "temperature", "type": "integer", "range": {"min": 16, "max": 30},
                 "mapping": [{"constraint": "temperature_unit", "conditions": [
                     {"dps_val": "fahrenheit", "value_redirect": "temperature_f"}
                 ]}]},
                {"id": 19, "name": "temperature_unit", "type": "string",
                 "mapping": [{"dps_val": "c", "value": "celsius"}, {"dps_val": "f", "value": "fahrenheit"}]},
                {"id": 20, "name": "temperature_f", "type": "integer", "range": {"min": 60, "max": 104}},
            ],
        }
        prepared, advanced, membership = productless._prepare_advanced_entity(entity, "climate")
        self.assertEqual({dp["name"] for dp in prepared["dps"]}, {"hvac_mode", "temperature", "temperature_unit"})
        self.assertIn(20, membership)
        self.assertEqual(advanced["2"][0]["conditions"][0]["value_redirect_dp"], 20)

    def test_semantic_constraint_dp_is_not_stripped(self):
        entity = {
            "entity": "climate",
            "dps": [
                {"id": 2, "name": "temperature", "type": "integer", "range": {"min": 16, "max": 30},
                 "mapping": [{"constraint": "temperature_unit", "conditions": [{"dps_val": "fahrenheit", "step": 1}]}]},
                {"id": 19, "name": "temperature_unit", "type": "string",
                 "mapping": [{"dps_val": "c", "value": "celsius"}, {"dps_val": "f", "value": "fahrenheit"}]},
            ],
        }
        prepared, _, _ = productless._prepare_advanced_entity(entity, "climate")
        self.assertIn("temperature_unit", {dp["name"] for dp in prepared["dps"]})


if __name__ == "__main__":
    unittest.main()
