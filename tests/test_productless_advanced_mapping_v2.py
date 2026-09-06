"""Batch M/Batсh O conditional metadata and enum projection tests."""

import unittest

import import_tuya_local_productless as productless


class ProductlessAdvancedMappingV2Tests(unittest.TestCase):
    def test_invalid_only_condition_keeps_base_enum_value(self):
        dp = {
            "id": 4, "type": "string", "name": "fan_mode",
            "mapping": [
                {"dps_val": "Low", "value": "low", "constraint": "mode",
                 "conditions": [{"dps_val": "Auto", "invalid": True}]},
                {"dps_val": "High", "value": "high", "constraint": "mode",
                 "conditions": [{"dps_val": "Auto", "invalid": True}]},
            ],
        }
        projected = productless._project_mapping_for_base(dp, "climate", "fan_mode")
        self.assertEqual(projected["mapping"], [
            {"dps_val": "low", "value": "low"},
            {"dps_val": "high", "value": "high"},
        ])

    def test_climate_condition_range_and_step_are_translated(self):
        dp = {
            "id": 16, "type": "integer", "name": "temperature",
            "range": {"min": 50, "max": 400},
            "mapping": [{
                "scale": 10, "step": 5, "constraint": "temperature_unit",
                "conditions": [{"dps_val": True, "range": {"min": 410, "max": 1040}, "step": 10}],
            }],
        }
        unit = {"id": 107, "type": "boolean", "name": "temperature_unit"}
        rules, refs = productless._translate_advanced_mapping(
            dp, {"temperature": dp, "temperature_unit": unit}, "climate"
        )
        self.assertEqual(refs, {"temperature_unit"})
        self.assertEqual(rules[0]["conditions"][0]["range"], {"min": 410, "max": 1040})
        self.assertEqual(rules[0]["conditions"][0]["step"], 10)
        self.assertNotIn("scale", rules[0])
        self.assertNotIn("step", rules[0])

    def test_fan_dynamic_step_is_translated(self):
        dp = {
            "id": 2, "type": "integer", "name": "speed",
            "mapping": [{"constraint": "preset_mode", "conditions": [{"dps_val": "sleep", "step": 4}]}],
        }
        preset = {"id": 3, "type": "string", "name": "preset_mode"}
        rules, refs = productless._translate_advanced_mapping(
            dp, {"speed": dp, "preset_mode": preset}, "fan"
        )
        self.assertEqual(refs, {"preset_mode"})
        self.assertEqual(rules[0]["conditions"][0]["step"], 4)

    def test_condition_scale_is_translated_relative_to_base_scale(self):
        dp = {
            "id": 2, "type": "integer", "name": "temperature",
            "mapping": [{"constraint": "mode", "conditions": [{"dps_val": "x", "scale": 10}]}],
        }
        mode = {"id": 3, "type": "string", "name": "mode"}
        rules, refs = productless._translate_advanced_mapping(
            dp, {"temperature": dp, "mode": mode}, "climate"
        )
        self.assertEqual(refs, {"mode"})
        self.assertEqual(rules[0]["conditions"][0]["scale"], 10.0)


if __name__ == "__main__":
    unittest.main()