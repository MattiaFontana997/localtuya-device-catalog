"""Tests for conservative Tuya Local climate importing."""

import unittest

from tools.import_tuya_local import ConversionError, convert_profile


def profile(dps):
    return {
        "name": "Thermostat",
        "products": [{"id": "climate-product"}],
        "entities": [{"entity": "climate", "dps": dps}],
    }


class TuyaLocalClimateImporterTests(unittest.TestCase):
    def test_scaled_heating_thermostat_converts(self):
        mapping = convert_profile(profile([
            {"id": 101, "name": "hvac_mode", "type": "boolean", "mapping": [
                {"dps_val": True, "value": "heat"},
                {"dps_val": False, "value": "off"},
            ]},
            {"id": 102, "name": "current_temperature", "type": "integer", "mapping": [{"scale": 10}]},
            {"id": 103, "name": "temperature", "type": "integer", "unit": "C", "range": {"min": 50, "max": 300}, "mapping": [{"scale": 10, "step": 5}]},
        ]), source_file="hama.yaml")
        config = mapping["entities"][0]["config"]
        self.assertEqual(config["hvac_mode_values"], {"heat": True, "off": False})
        self.assertEqual(config["target_precision"], 0.1)
        self.assertEqual(config["temperature_step"], 0.5)
        self.assertEqual(config["min_temperature_const"], 5.0)
        self.assertEqual(config["max_temperature_const"], 30.0)
        self.assertEqual(config["precision"], 0.1)

    def test_boolean_preset_keeps_exact_raw_values(self):
        mapping = convert_profile(profile([
            {"id": 1, "name": "hvac_mode", "type": "boolean", "mapping": [
                {"dps_val": True, "value": "heat"}, {"dps_val": False, "value": "off"}]},
            {"id": 2, "name": "temperature", "type": "integer", "range": {"min": 0, "max": 37}},
            {"id": 6, "name": "preset_mode", "type": "boolean", "mapping": [
                {"dps_val": True, "value": "eco"}, {"dps_val": False, "value": "comfort"}]},
        ]), source_file="eurom.yaml")
        config = mapping["entities"][0]["config"]
        self.assertEqual(config["preset_values"], {"eco": True, "comfort": False})

    def test_enum_modes_actions_fan_and_swing_convert(self):
        mapping = convert_profile(profile([
            {"id": 1, "name": "hvac_mode", "type": "string", "mapping": [
                {"dps_val": "poweroff", "value": "off"},
                {"dps_val": "hot", "value": "heat"},
                {"dps_val": "cold", "value": "cool"}]},
            {"id": 4, "name": "fan_mode", "type": "string", "mapping": [
                {"dps_val": "low", "value": "low"}, {"dps_val": "high", "value": "high"}]},
            {"id": 5, "name": "swing_mode", "type": "boolean", "mapping": [
                {"dps_val": True, "value": "on"}, {"dps_val": False, "value": "off"}]},
            {"id": 6, "name": "hvac_action", "type": "string", "mapping": [
                {"dps_val": "working", "value": "heating"}, {"dps_val": "idle", "value": "idle"}]},
        ]), source_file="ac.yaml")
        config = mapping["entities"][0]["config"]
        self.assertEqual(config["hvac_mode_values"]["off"], "poweroff")
        self.assertEqual(config["hvac_fan_mode_values"]["high"], "high")
        self.assertEqual(config["hvac_swing_mode_values"]["on"], True)
        self.assertEqual(config["hvac_action_values"]["heating"], "working")

    def test_target_range_and_humidity_convert(self):
        mapping = convert_profile(profile([
            {"id": 1, "name": "hvac_mode", "type": "boolean", "mapping": [
                {"dps_val": True, "value": "heat"}, {"dps_val": False, "value": "off"}]},
            {"id": 10, "name": "target_temp_low", "type": "integer", "range": {"min": 50, "max": 250}, "mapping": [{"scale": 10}]},
            {"id": 11, "name": "target_temp_high", "type": "integer", "range": {"min": 150, "max": 350}, "mapping": [{"scale": 10}]},
            {"id": 12, "name": "humidity", "type": "integer", "range": {"min": 30, "max": 90}},
            {"id": 13, "name": "current_humidity", "type": "integer"},
        ]), source_file="range.yaml")
        config = mapping["entities"][0]["config"]
        self.assertEqual(config["target_temperature_low_precision"], 0.1)
        self.assertEqual(config["target_temperature_high_precision"], 0.1)
        self.assertEqual(config["target_humidity_dp"], 12)
        self.assertEqual(config["min_humidity_const"], 30.0)

    def test_simple_visible_extra_attribute_is_preserved(self):
        mapping = convert_profile(profile([
            {"id": 1, "name": "hvac_mode", "type": "boolean", "mapping": [
                {"dps_val": True, "value": "heat"}, {"dps_val": False, "value": "off"}]},
            {"id": 50, "name": "mode", "type": "string"},
        ]), source_file="extra.yaml")
        config = mapping["entities"][0]["config"]
        self.assertEqual(config["extra_state_attributes_dps"], {"mode": 50})

    def test_hidden_extra_affects_matching_but_not_attributes(self):
        mapping = convert_profile(profile([
            {"id": 1, "name": "hvac_mode", "type": "boolean", "mapping": [
                {"dps_val": True, "value": "heat"}, {"dps_val": False, "value": "off"}]},
            {"id": 50, "name": "mode", "type": "string", "hidden": True},
        ]), source_file="hidden.yaml")
        config = mapping["entities"][0]["config"]
        self.assertNotIn("extra_state_attributes_dps", config)
        self.assertIn(50, mapping["match"]["required_dps"])

    def test_constraint_stays_fail_closed(self):
        with self.assertRaisesRegex(ConversionError, "advanced_mapping"):
            convert_profile(profile([
                {"id": 1, "name": "hvac_mode", "type": "boolean", "mapping": [
                    {"dps_val": True, "value": "heat"}, {"dps_val": False, "value": "off"}]},
                {"id": 2, "name": "temperature", "type": "integer", "range": {"min": 5, "max": 35},
                 "mapping": [{"scale": 10, "constraint": "mode"}]},
            ]), source_file="conditional.yaml")

    def test_unknown_mapped_extra_stays_fail_closed(self):
        with self.assertRaisesRegex(ConversionError, "climate_extra_mapping"):
            convert_profile(profile([
                {"id": 1, "name": "hvac_mode", "type": "boolean", "mapping": [
                    {"dps_val": True, "value": "heat"}, {"dps_val": False, "value": "off"}]},
                {"id": 44, "name": "mystery", "type": "string", "mapping": [
                    {"dps_val": "x", "value": "y"}]},
            ]), source_file="mystery.yaml")


if __name__ == "__main__":
    unittest.main()
