"""Tests for conservative Tuya Local vacuum importing."""

import unittest

from tools.import_tuya_local import ConversionError, convert_profile


def profile(dps):
    return {
        "name": "Vacuum",
        "products": [{"id": "vacuum-product"}],
        "entities": [{"entity": "vacuum", "dps": dps}],
    }


class TuyaLocalVacuumImporterTests(unittest.TestCase):
    def base_status(self):
        return {"id": 5, "name": "status", "type": "string", "mapping": [
            {"dps_val": "standby_raw", "value": "standby"},
            {"dps_val": "clean_raw", "value": "cleaning"},
            {"dps_val": "charge_raw", "value": "charging"},
        ]}

    def test_core_vacuum_mappings_convert_exactly(self):
        mapping = convert_profile(profile([
            self.base_status(),
            {"id": 1, "name": "power", "type": "boolean"},
            {"id": 2, "name": "activate", "type": "boolean"},
            {"id": 3, "name": "command", "type": "string", "mapping": [
                {"dps_val": "go", "value": "start"},
                {"dps_val": "dock_raw", "value": "return_to_base"},
                {"dps_val": "halt", "value": "stop"},
            ]},
            {"id": 6, "name": "fan_speed", "type": "string", "mapping": [
                {"dps_val": "q", "value": "quiet"}, {"dps_val": "t", "value": "turbo"}]},
            {"id": 7, "name": "direction_control", "type": "string", "mapping": [
                {"dps_val": "L", "value": "left"}, {"dps_val": "S", "value": "stop"}]},
            {"id": 8, "name": "locate", "type": "boolean", "optional": True},
            {"id": 9, "name": "error", "type": "bitfield", "hidden": True},
        ]), source_file="vacuum.yaml")
        config = mapping["entities"][0]["config"]
        self.assertEqual(config["vacuum_status_values"]["charging"], "charge_raw")
        self.assertEqual(config["vacuum_command_values"]["return_to_base"], "dock_raw")
        self.assertEqual(config["vacuum_fan_speed_values"]["turbo"], "t")
        self.assertEqual(config["vacuum_direction_values"]["stop"], "S")
        self.assertTrue(config["vacuum_power_on"])
        self.assertFalse(config["vacuum_activate_off"])
        self.assertIn(8, mapping["match"]["optional_dps"])

    def test_mapped_boolean_activate_preserves_raw_values(self):
        mapping = convert_profile(profile([
            self.base_status(),
            {"id": 2, "name": "activate", "type": "string", "mapping": [
                {"dps_val": "running", "value": True},
                {"dps_val": "paused", "value": False},
            ]},
        ]), source_file="mapped-activate.yaml")
        config = mapping["entities"][0]["config"]
        self.assertEqual(config["vacuum_activate_on"], "running")
        self.assertEqual(config["vacuum_activate_off"], "paused")

    def test_simple_robot_data_is_preserved(self):
        mapping = convert_profile(profile([
            self.base_status(),
            {"id": 20, "name": "device_info", "type": "base64", "optional": True},
            {"id": 21, "name": "clean_record", "type": "string"},
        ]), source_file="extras.yaml")
        config = mapping["entities"][0]["config"]
        self.assertEqual(config["extra_state_attributes_dps"], {"device_info": 20, "clean_record": 21})

    def test_hidden_extra_matches_but_is_not_exposed(self):
        mapping = convert_profile(profile([
            self.base_status(),
            {"id": 20, "name": "pause", "type": "boolean", "hidden": True},
        ]), source_file="hidden.yaml")
        config = mapping["entities"][0]["config"]
        self.assertNotIn("extra_state_attributes_dps", config)
        self.assertIn(20, mapping["match"]["required_dps"])

    def test_optional_status_stays_fail_closed(self):
        status = self.base_status()
        status["optional"] = True
        with self.assertRaisesRegex(ConversionError, "vacuum_optional_status"):
            convert_profile(profile([status]), source_file="optional-status.yaml")

    def test_advanced_command_stays_fail_closed(self):
        with self.assertRaisesRegex(ConversionError, "advanced_mapping"):
            convert_profile(profile([
                self.base_status(),
                {"id": 3, "name": "command", "type": "string", "mapping": [
                    {"dps_val": "go", "value": "start", "constraint": "mode"}]},
            ]), source_file="advanced.yaml")

    def test_mapped_extra_stays_fail_closed(self):
        with self.assertRaisesRegex(ConversionError, "vacuum_extra_mapping"):
            convert_profile(profile([
                self.base_status(),
                {"id": 20, "name": "mode", "type": "string", "mapping": [
                    {"dps_val": "a", "value": "b"}]},
            ]), source_file="mapped-extra.yaml")


if __name__ == "__main__":
    unittest.main()
