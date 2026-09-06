"""Batch L productless water-heater importer tests."""

import unittest

import import_tuya_local as base
import import_tuya_local_productless as productless


class ProductlessWaterHeaterTests(unittest.TestCase):
    def test_static_boolean_mode_temperature_away_and_extras_convert(self):
        entity = {
            "entity": "water_heater",
            "dps": [
                {"id": 1, "type": "boolean", "name": "operation_mode", "mapping": [
                    {"dps_val": False, "value": "off"},
                    {"dps_val": True, "value": "electric"},
                ]},
                {"id": 9, "type": "integer", "name": "temperature", "unit": "C", "range": {"min": 35, "max": 75}},
                {"id": 13, "type": "string", "name": "work_mode"},
                {"id": 20, "type": "integer", "name": "attr1"},
                {"id": 101, "type": "boolean", "name": "away_mode"},
                {"id": 102, "type": "integer", "name": "current_temperature"},
            ],
        }
        converted, required, optional = productless._convert_water_heater_productless(entity)
        config = converted["config"]
        self.assertEqual(config["water_heater_mode_values"], {"off": False, "electric": True})
        self.assertEqual(config["water_heater_power_dp"], 1)
        self.assertEqual(config["water_heater_target_temperature_dp"], 9)
        self.assertEqual(config["water_heater_current_temperature_dp"], 102)
        self.assertEqual(config["water_heater_temperature_unit"], "°C")
        self.assertEqual(config["water_heater_away_dp"], 101)
        self.assertEqual(config["extra_state_attributes_dps"], {"work_mode": 13, "attr1": 20})
        self.assertEqual(required, {1, 9, 13, 20, 101, 102})
        self.assertEqual(optional, set())

    def test_conditioned_boolean_mode_projects_to_logical_mode_domain(self):
        entity = {
            "entity": "water_heater",
            "dps": [
                {"id": 1, "type": "boolean", "name": "operation_mode", "mapping": [
                    {"dps_val": False, "value": "off"},
                    {"dps_val": True, "constraint": "work_mode", "conditions": [
                        {"dps_val": "ECO", "value": "eco"},
                        {"dps_val": "STANDARD", "value": "heat_pump"},
                        {"dps_val": "ELEMENT", "value": "electric"},
                    ]},
                ]},
                {"id": 2, "type": "integer", "name": "temperature", "unit": "C", "range": {"min": 15, "max": 75}},
                {"id": 3, "type": "integer", "name": "current_temperature"},
                {"id": 4, "type": "string", "name": "work_mode", "hidden": True},
            ],
        }
        converted, required, optional = base._CONVERTERS["water_heater"](entity)
        config = converted["config"]
        self.assertEqual(config["water_heater_power_on"], True)
        self.assertEqual(config["water_heater_power_off"], False)
        self.assertEqual(
            config["water_heater_mode_values"],
            {"off": "off", "eco": "eco", "heat_pump": "heat_pump", "electric": "electric"},
        )
        self.assertIn("1", config["advanced_mapping_by_dp"])
        self.assertEqual(required, {1, 2, 3, 4})
        self.assertEqual(optional, set())
        self.assertNotIn("work_mode", config.get("extra_state_attributes_dps", {}))

    def test_dynamic_fahrenheit_range_remains_fail_closed(self):
        entity = {
            "entity": "water_heater",
            "dps": [
                {"id": 2, "type": "integer", "name": "current_temperature"},
                {"id": 8, "type": "integer", "name": "temperature", "range": {"min": 0, "max": 100}, "mapping": [
                    {"constraint": "temperature_unit", "conditions": [
                        {"dps_val": "f", "value_redirect": "temp_set_f", "range": {"min": 32, "max": 212}},
                    ]},
                ]},
                {"id": 9, "type": "integer", "name": "temp_set_f", "range": {"min": 32, "max": 212}},
                {"id": 12, "type": "string", "name": "temperature_unit"},
            ],
        }
        with self.assertRaisesRegex(base.ConversionError, "advanced_mapping_condition_semantics"):
            base._CONVERTERS["water_heater"](entity)

    def test_mismatched_temperature_scales_fail_closed(self):
        entity = {
            "entity": "water_heater",
            "dps": [
                {"id": 1, "type": "boolean", "name": "operation_mode", "mapping": [
                    {"dps_val": False, "value": "off"}, {"dps_val": True, "value": "electric"}
                ]},
                {"id": 2, "type": "integer", "name": "temperature", "range": {"min": 10, "max": 60}, "mapping": [{"scale": 10}]},
                {"id": 3, "type": "integer", "name": "current_temperature"},
            ],
        }
        with self.assertRaisesRegex(base.ConversionError, "water_heater_temperature_scale_mismatch"):
            productless._convert_water_heater_productless(entity)


if __name__ == "__main__":
    unittest.main()
