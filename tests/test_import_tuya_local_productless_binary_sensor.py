import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from import_tuya_local_productless import ConversionError, convert_profile


class ProductlessBinarySensorConverterTests(unittest.TestCase):
    def _convert(self, dp, *, entity_extra=None):
        entity = {"entity": "binary_sensor", "dps": [dp]}
        if entity_extra:
            entity.update(entity_extra)
        profile = {
            "name": "Batch H test",
            "products": [{"id": "batch-h-test"}],
            "entities": [entity],
        }
        return convert_profile(profile, source_file="batch_h_test.yaml")

    def test_bitfield_mask_mapping_uses_extended_runtime_grammar(self):
        result = self._convert({
            "id": 19,
            "type": "bitfield",
            "name": "sensor",
            "mapping": [
                {"dps_val": 4, "value": True},
                {"value": False},
            ],
        })
        config = result["entities"][0]["config"]
        self.assertIs(config["binary_sensor_bitfield"], True)
        self.assertEqual(config["binary_sensor_mapping"], [
            {"dps_val": 4, "value": True},
            {"value": False},
        ])

    def test_bitfield_problem_mapping_preserves_ordered_catch_all(self):
        result = self._convert({
            "id": 9,
            "type": "bitfield",
            "name": "sensor",
            "mapping": [
                {"dps_val": 0, "value": False},
                {"dps_val": 1, "value": False},
                {"dps_val": 2, "value": False},
                {"value": True},
            ],
        })
        self.assertEqual(
            result["entities"][0]["config"]["binary_sensor_mapping"][-1],
            {"value": True},
        )

    def test_integer_default_mapping_is_lossless(self):
        result = self._convert({
            "id": 1,
            "type": "integer",
            "name": "sensor",
            "mapping": [
                {"dps_val": 1, "value": True},
                {"value": False},
            ],
        })
        config = result["entities"][0]["config"]
        self.assertNotIn("binary_sensor_bitfield", config)
        self.assertEqual(config["binary_sensor_mapping"][1], {"value": False})

    def test_string_multiple_true_values_are_preserved(self):
        result = self._convert({
            "id": 1,
            "type": "string",
            "name": "sensor",
            "mapping": [
                {"dps_val": "small_move", "value": True},
                {"dps_val": "large_move", "value": True},
                {"value": False},
            ],
        })
        config = result["entities"][0]["config"]
        self.assertEqual(len(config["binary_sensor_mapping"]), 3)

    def test_existing_exact_mapping_keeps_legacy_output(self):
        result = self._convert({
            "id": 25,
            "type": "string",
            "name": "sensor",
            "mapping": [
                {"dps_val": "on", "value": True},
                {"dps_val": "off", "value": False},
            ],
        })
        config = result["entities"][0]["config"]
        self.assertEqual(config["state_on"], "on")
        self.assertEqual(config["state_off"], "off")
        self.assertNotIn("binary_sensor_mapping", config)

    def test_null_bitfield_rule_is_preserved_exactly(self):
        result = self._convert({
            "id": 19,
            "type": "bitfield",
            "name": "sensor",
            "mapping": [
                {"dps_val": 0, "value": False},
                {"dps_val": None, "value": False},
                {"value": True},
            ],
        })
        self.assertIsNone(
            result["entities"][0]["config"]["binary_sensor_mapping"][1]["dps_val"]
        )

    def test_non_boolean_output_stays_fail_closed(self):
        with self.assertRaisesRegex(ConversionError, "binary_sensor_non_boolean_mapping"):
            self._convert({
                "id": 1,
                "type": "integer",
                "name": "sensor",
                "mapping": [
                    {"dps_val": 1, "value": "alarm"},
                    {"value": False},
                ],
            })


if __name__ == "__main__":
    unittest.main()
