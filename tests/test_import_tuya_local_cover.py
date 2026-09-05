"""Tests for conservative Tuya Local cover importing."""

import unittest

from tools.import_tuya_local import ConversionError, convert_profile


def profile(dps):
    return {
        "name": "Cover",
        "products": [{"id": "cover-product"}],
        "entities": [{"entity": "cover", "dps": dps}],
    }


class TuyaLocalCoverImporterTests(unittest.TestCase):
    def test_control_positions_and_action_convert(self):
        mapping = convert_profile(profile([
            {"id": 1, "name": "control", "type": "string", "mapping": [
                {"dps_val": "up", "value": "open"},
                {"dps_val": "down", "value": "close"},
                {"dps_val": "halt", "value": "stop"},
            ]},
            {"id": 2, "name": "position", "type": "integer", "range": {"min": 0, "max": 100}, "mapping": [{"invert": True, "step": 5}]},
            {"id": 3, "name": "current_position", "type": "integer", "range": {"min": 0, "max": 100}, "mapping": [{"invert": True}]},
            {"id": 4, "name": "action", "type": "string", "mapping": [
                {"dps_val": "opening_raw", "value": "opening"},
                {"dps_val": "closing_raw", "value": "closing"},
                {"dps_val": "closed_raw", "value": "closed"},
            ]},
        ]), source_file="cover.yaml")
        config = mapping["entities"][0]["config"]
        self.assertEqual(config["cover_command_values"], {"open": "up", "close": "down", "stop": "halt"})
        self.assertEqual(config["set_position_step"], 5.0)
        self.assertTrue(config["set_position_inverted"])
        self.assertEqual(config["cover_action_values"]["opening"], "opening_raw")

    def test_position_only_explicitly_disables_legacy_commands(self):
        mapping = convert_profile(profile([
            {"id": 2, "name": "position", "type": "integer", "range": {"min": 0, "max": 100}},
        ]), source_file="position.yaml")
        config = mapping["entities"][0]["config"]
        self.assertEqual(config["cover_command_values"], {})
        self.assertEqual(config["set_position_dp"], 2)
        self.assertEqual(config["positioning_mode"], "position")

    def test_boolean_open_and_tilt_convert(self):
        mapping = convert_profile(profile([
            {"id": 1, "name": "control", "type": "string", "mapping": [
                {"dps_val": "open", "value": "open"}, {"dps_val": "close", "value": "close"}]},
            {"id": 5, "name": "open", "type": "boolean"},
            {"id": 6, "name": "tilt_position", "type": "integer", "range": {"min": 10, "max": 50}},
        ]), source_file="tilt.yaml")
        config = mapping["entities"][0]["config"]
        self.assertEqual(config["cover_open_values"], {"open": True, "closed": False})
        self.assertEqual(config["tilt_position_min"], 10.0)
        self.assertEqual(config["tilt_position_max"], 50.0)

    def test_simple_extra_attribute_is_preserved(self):
        mapping = convert_profile(profile([
            {"id": 1, "name": "control", "type": "string", "mapping": [
                {"dps_val": "open", "value": "open"}, {"dps_val": "close", "value": "close"}]},
            {"id": 20, "name": "learning_state", "type": "string", "optional": True},
        ]), source_file="extra.yaml")
        config = mapping["entities"][0]["config"]
        self.assertEqual(config["extra_state_attributes_dps"], {"learning_state": 20})
        self.assertIn(20, mapping["match"]["optional_dps"])

    def test_mapped_extra_stays_fail_closed(self):
        with self.assertRaisesRegex(ConversionError, "cover_extra_mapping"):
            convert_profile(profile([
                {"id": 1, "name": "control", "type": "string", "mapping": [
                    {"dps_val": "open", "value": "open"}, {"dps_val": "close", "value": "close"}]},
                {"id": 20, "name": "work_state", "type": "string", "mapping": [
                    {"dps_val": "x", "value": "y"}]},
            ]), source_file="mapped-extra.yaml")

    def test_advanced_control_mapping_stays_fail_closed(self):
        with self.assertRaisesRegex(ConversionError, "advanced_mapping"):
            convert_profile(profile([
                {"id": 1, "name": "control", "type": "string", "mapping": [
                    {"dps_val": "open", "value": "open", "constraint": "mode"}]},
            ]), source_file="advanced.yaml")


if __name__ == "__main__":
    unittest.main()
