"""Tests for conservative Tuya Local core platform importing."""

import unittest

from tools.import_tuya_local import ConversionError, convert_profile


def profile(entity, dps, **entity_extra):
    item = {"entity": entity, "dps": dps, **entity_extra}
    return {
        "name": "Core platform",
        "products": [{"id": "core-product"}],
        "entities": [item],
    }


class TuyaLocalCorePlatformImporterTests(unittest.TestCase):
    def test_button_preserves_exact_string_trigger(self):
        mapping = convert_profile(profile("button", [
            {"id": 101, "name": "button", "type": "string", "mapping": [
                {"dps_val": "forceReset", "value": True},
            ]},
        ]), source_file="button.yaml")
        config = mapping["entities"][0]["config"]
        self.assertEqual(config["button_press_value"], "forceReset")

    def test_button_ambiguous_true_mapping_fails_closed(self):
        with self.assertRaisesRegex(ConversionError, "button_press_mapping"):
            convert_profile(profile("button", [
                {"id": 101, "name": "button", "type": "string", "mapping": [
                    {"dps_val": "a", "value": True},
                    {"dps_val": "b", "value": True},
                ]},
            ]), source_file="button-ambiguous.yaml")

    def test_text_hidden_dp_becomes_password_mode(self):
        mapping = convert_profile(profile("text", [
            {"id": 8, "name": "value", "type": "string", "hidden": True,
             "range": {"min": 4, "max": 32}},
        ]), source_file="text.yaml")
        config = mapping["entities"][0]["config"]
        self.assertEqual(config["text_mode"], "password")
        self.assertEqual(config["text_min"], 4)
        self.assertEqual(config["text_max"], 32)

    def test_sensitive_text_fails_closed(self):
        with self.assertRaisesRegex(ConversionError, "text_sensitive_semantics"):
            convert_profile(profile("text", [
                {"id": 8, "name": "value", "type": "base64", "sensitive": True},
            ]), source_file="text-sensitive.yaml")

    def test_boolean_valve_converts(self):
        mapping = convert_profile(profile("valve", [
            {"id": 1, "name": "valve", "type": "boolean"},
        ], **{"class": "water"}), source_file="valve.yaml")
        config = mapping["entities"][0]["config"]
        self.assertEqual(config["valve_open_value"], True)
        self.assertEqual(config["valve_closed_value"], False)
        self.assertEqual(config["device_class"], "water")

    def test_position_valve_preserves_range_and_inversion(self):
        mapping = convert_profile(profile("valve", [
            {"id": 1, "name": "valve", "type": "integer", "range": {"min": 20, "max": 80},
             "mapping": [{"invert": True}]},
            {"id": 2, "name": "current_position", "type": "integer", "range": {"min": 20, "max": 80},
             "mapping": [{"invert": True}], "optional": True},
        ]), source_file="valve-position.yaml")
        config = mapping["entities"][0]["config"]
        self.assertTrue(config["valve_position_control"])
        self.assertEqual(config["valve_position_min"], 20.0)
        self.assertEqual(config["valve_position_max"], 80.0)
        self.assertTrue(config["valve_position_inverted"])
        self.assertIn(2, mapping["match"]["optional_dps"])

    def test_direct_lock_preserves_inverted_raw_values(self):
        mapping = convert_profile(profile("lock", [
            {"id": 46, "name": "lock", "type": "string", "mapping": [
                {"dps_val": "closed_raw", "value": True},
                {"dps_val": "open_raw", "value": False},
            ]},
            {"id": 47, "name": "lock_state", "type": "boolean", "mapping": [
                {"dps_val": True, "value": False},
                {"dps_val": False, "value": True},
            ]},
        ]), source_file="lock.yaml")
        config = mapping["entities"][0]["config"]
        self.assertEqual(config["lock_command_values"], {"lock": "closed_raw", "unlock": "open_raw"})
        self.assertEqual(config["lock_state_values"], {"locked": False, "unlocked": True})

    def test_special_lock_protocol_fails_closed(self):
        with self.assertRaisesRegex(ConversionError, "lock_unsupported_dp:code_unlock"):
            convert_profile(profile("lock", [
                {"id": 1, "name": "lock", "type": "boolean"},
                {"id": 61, "name": "code_unlock", "type": "base64", "optional": True},
            ]), source_file="coded-lock.yaml")

    def test_humidifier_preserves_scaling_range_mode_and_action(self):
        mapping = convert_profile(profile("humidifier", [
            {"id": 1, "name": "switch", "type": "boolean"},
            {"id": 2, "name": "current_humidity", "type": "integer", "mapping": [{"scale": 10}]},
            {"id": 3, "name": "humidity", "type": "integer", "range": {"min": 300, "max": 800},
             "mapping": [{"scale": 10, "step": 10}]},
            {"id": 4, "name": "mode", "type": "string", "mapping": [
                {"dps_val": "A", "value": "auto"}, {"dps_val": "S", "value": "sleep"}]},
            {"id": 5, "name": "action", "type": "string", "mapping": [
                {"dps_val": "work", "value": "humidifying"}, {"dps_val": "idle_raw", "value": "idle"}]},
        ], **{"class": "humidifier"}), source_file="humidifier.yaml")
        config = mapping["entities"][0]["config"]
        self.assertEqual(config["humidifier_humidity_scaling"], 0.1)
        self.assertEqual(config["humidifier_humidity_min"], 30.0)
        self.assertEqual(config["humidifier_humidity_max"], 80.0)
        self.assertEqual(config["humidifier_humidity_step"], 1.0)
        self.assertEqual(config["humidifier_mode_values"]["sleep"], "S")
        self.assertEqual(config["humidifier_action_values"]["humidifying"], "work")

    def test_humidity_scale_mismatch_fails_closed(self):
        with self.assertRaisesRegex(ConversionError, "humidifier_humidity_scaling_mismatch"):
            convert_profile(profile("humidifier", [
                {"id": 2, "name": "current_humidity", "type": "integer", "mapping": [{"scale": 10}]},
                {"id": 3, "name": "humidity", "type": "integer", "range": {"min": 30, "max": 80}},
            ]), source_file="humidity-mismatch.yaml")


if __name__ == "__main__":
    unittest.main()
