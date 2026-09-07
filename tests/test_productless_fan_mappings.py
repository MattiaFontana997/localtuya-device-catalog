import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from import_tuya_local_productless import ConversionError, convert_profile


class ProductlessFanMappingTests(unittest.TestCase):
    def _convert(self, dps):
        return convert_profile(
            {
                "name": "Batch K fan",
                "products": [{"id": "batch-k-test"}],
                "entities": [{"entity": "fan", "dps": dps}],
            },
            source_file="batch_k_fan.yaml",
        )

    def test_custom_speed_percentages_are_preserved_exactly(self):
        result = self._convert([
            {"id": 1, "name": "switch", "type": "boolean"},
            {"id": 3, "name": "speed", "type": "string", "mapping": [
                {"dps_val": "1", "value": 13},
                {"dps_val": "2", "value": 25},
                {"dps_val": "3", "value": 37},
                {"dps_val": "4", "value": 50},
            ]},
        ])
        config = result["entities"][0]["config"]
        self.assertEqual(config["fan_speed_mapping"]["rules"][0], {"dps_val": "1", "value": 13})
        self.assertEqual(config["fan_speed_control"], 3)

    def test_string_speed_dp_normalizes_yaml_integer_raws(self):
        result = self._convert([
            {"id": 1, "name": "switch", "type": "boolean"},
            {"id": 4, "name": "speed", "type": "string", "mapping": [
                {"dps_val": "S", "value": 20},
                {"dps_val": 1, "value": 40},
                {"dps_val": 2, "value": 100},
            ]},
        ])
        rules = result["entities"][0]["config"]["fan_speed_mapping"]["rules"]
        self.assertEqual([rule["dps_val"] for rule in rules], ["S", "1", "2"])

    def test_multiple_false_oscillation_values_remain_readable(self):
        result = self._convert([
            {"id": 1, "name": "switch", "type": "boolean"},
            {"id": 102, "name": "oscillate", "type": "string", "mapping": [
                {"dps_val": "90", "value": False},
                {"dps_val": "45", "value": False},
                {"dps_val": "45_90", "value": True},
            ]},
        ])
        config = result["entities"][0]["config"]
        self.assertEqual(len(config["fan_oscillating_mapping"]["rules"]), 3)

    def test_oscillation_default_is_kept_as_read_fallback(self):
        result = self._convert([
            {"id": 1, "name": "switch", "type": "boolean"},
            {"id": 102, "name": "oscillate", "type": "string", "mapping": [
                {"dps_val": "0_90", "value": True},
                {"dps_val": "90", "value": False},
                {"value": False},
            ]},
        ])
        self.assertEqual(
            result["entities"][0]["config"]["fan_oscillating_mapping"]["rules"][-1],
            {"value": False},
        )

    def test_boolean_optional_preset_keeps_typed_raw_values(self):
        result = self._convert([
            {"id": 1, "name": "switch", "type": "boolean"},
            {"id": 105, "name": "preset_mode", "type": "boolean", "optional": True, "mapping": [
                {"dps_val": True, "value": "auto"},
                {"dps_val": False, "value": "manual"},
            ]},
        ])
        config = result["entities"][0]["config"]
        self.assertEqual(config["fan_preset_raw_type"], "boolean")
        self.assertIs(config["fan_preset_values"]["auto"], True)
        self.assertIn(105, result["match"]["optional_dps"])

    def test_simple_fan_extra_dp_is_preserved(self):
        result = self._convert([
            {"id": 1, "name": "switch", "type": "boolean"},
            {"id": 4, "name": "speed", "type": "integer", "range": {"min": 1, "max": 100}},
            {"id": 3, "name": "fan_level", "type": "string"},
        ])
        self.assertEqual(
            result["entities"][0]["config"]["extra_state_attributes_dps"],
            {"fan_level": 3},
        )

    def test_switchless_fan_uses_explicit_no_switch_runtime_flag(self):
        result = self._convert([
            {"id": 102, "name": "speed", "type": "string", "mapping": [
                {"dps_val": "0", "value": 10},
                {"dps_val": "9", "value": 100},
            ]},
        ])
        config = result["entities"][0]["config"]
        self.assertIs(config["fan_no_switch"], True)
        self.assertEqual(config["id"], 102)
        self.assertEqual(config["fan_speed_control"], 102)
        self.assertEqual(result["match"]["required_dps"], [102])


if __name__ == "__main__":
    unittest.main()
