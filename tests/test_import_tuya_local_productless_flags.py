import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from import_tuya_local_productless import ConversionError, convert_profile


class ProductlessRuntimeFlagTests(unittest.TestCase):
    def _convert(self, entities):
        return convert_profile(
            {
                "name": "Batch I test",
                "products": [{"id": "batch-i-test"}],
                "entities": entities,
            },
            source_file="batch_i_test.yaml",
        )

    def test_hidden_entity_is_disabled_by_default(self):
        result = self._convert([{
            "entity": "switch",
            "hidden": True,
            "dps": [{"id": 1, "name": "switch", "type": "boolean"}],
        }])
        config = result["entities"][0]["config"]
        self.assertIs(config["entity_registry_enabled_default"], False)

    def test_hidden_unavailable_stays_fail_closed(self):
        with self.assertRaisesRegex(ConversionError, "entity_hidden_unavailable"):
            self._convert([{
                "entity": "switch",
                "hidden": "unavailable",
                "dps": [{"id": 1, "name": "switch", "type": "boolean"}],
            }])

    def test_force_primary_is_consumed_without_catalog_flag(self):
        result = self._convert([{
            "entity": "sensor",
            "dps": [{"id": 18, "name": "sensor", "type": "integer", "force": True}],
        }])
        config = result["entities"][0]["config"]
        self.assertEqual(config["id"], 18)
        self.assertNotIn("force", config)

    def test_force_extra_remains_requested_as_raw_attribute(self):
        result = self._convert([{
            "entity": "sensor",
            "dps": [
                {"id": 18, "name": "sensor", "type": "integer"},
                {"id": 23, "name": "calibration", "type": "integer", "force": True, "optional": True},
            ],
        }])
        config = result["entities"][0]["config"]
        self.assertEqual(config["extra_state_attributes_dps"], {"calibration": 23})
        self.assertIn(23, result["match"]["optional_dps"])

    def test_hidden_extra_stays_in_fingerprint_but_not_attributes(self):
        result = self._convert([{
            "entity": "sensor",
            "dps": [
                {"id": 7, "name": "sensor", "type": "integer"},
                {"id": 8, "name": "level", "type": "string", "hidden": True, "optional": True},
            ],
        }])
        config = result["entities"][0]["config"]
        self.assertNotIn("extra_state_attributes_dps", config)
        self.assertIn(8, result["match"]["optional_dps"])

    def test_persist_false_primary_becomes_runtime_cache_policy(self):
        result = self._convert([{
            "entity": "sensor",
            "dps": [{
                "id": 3,
                "name": "sensor",
                "type": "integer",
                "persist": False,
                "optional": True,
                "mapping": [{"scale": 1000}],
            }],
        }])
        config = result["entities"][0]["config"]
        self.assertEqual(config["non_persistent_dps"], [3])
        self.assertIn(3, result["match"]["optional_dps"])

    def test_persist_false_bitfield_keeps_batch_h_mapping(self):
        result = self._convert([{
            "entity": "binary_sensor",
            "dps": [{
                "id": 12,
                "name": "sensor",
                "type": "bitfield",
                "persist": False,
                "optional": True,
                "mapping": [
                    {"dps_val": 0, "value": False},
                    {"dps_val": None, "value": False},
                    {"value": True},
                ],
            }],
        }])
        config = result["entities"][0]["config"]
        self.assertIs(config["binary_sensor_bitfield"], True)
        self.assertEqual(config["non_persistent_dps"], [12])


if __name__ == "__main__":
    unittest.main()
