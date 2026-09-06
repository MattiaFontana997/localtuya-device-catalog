"""Batch O lossless advanced-mapping importer regressions."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from import_tuya_local_productless import convert_profile  # noqa: E402


class BatchOImporterTests(unittest.TestCase):
    def _convert(self, entities):
        return convert_profile({"name": "Test", "products": [{"id": "synthetic"}], "entities": entities}, source_file="test.yaml")

    def test_climate_condition_scale_is_relative_to_base_scale(self):
        result = self._convert([{
            "entity": "climate",
            "dps": [
                {"id": 1, "name": "hvac_mode", "type": "boolean", "mapping": [{"dps_val": False, "value": "off"}, {"dps_val": True, "value": "heat"}]},
                {"id": 2, "name": "temperature", "type": "integer", "range": {"min": 50, "max": 350}, "mapping": [{"scale": 10}]},
                {"id": 3, "name": "current_temperature", "type": "integer", "mapping": [{"scale": 10, "constraint": "unit", "conditions": [{"dps_val": "f", "scale": 5}]}]},
                {"id": 4, "name": "unit", "type": "string", "hidden": True},
            ],
        }])
        config = result["entities"][0]["config"]
        self.assertEqual(config["advanced_mapping_by_dp"]["3"][0]["conditions"][0]["scale"], 0.5)
        self.assertEqual(result["match"]["required_dps"], [1, 2, 3, 4])

    def test_fan_condition_step_is_preserved(self):
        result = self._convert([{
            "entity": "fan",
            "dps": [
                {"id": 1, "name": "switch", "type": "boolean"},
                {"id": 2, "name": "speed", "type": "integer", "range": {"min": 1, "max": 12}, "mapping": [{"constraint": "preset_mode", "conditions": [{"dps_val": "nature", "step": 4}]}]},
                {"id": 3, "name": "preset_mode", "type": "string", "mapping": [{"dps_val": "normal", "value": "normal"}, {"dps_val": "nature", "value": "nature"}]},
            ],
        }])
        config = result["entities"][0]["config"]
        self.assertEqual(config["advanced_mapping_by_dp"]["2"][0]["conditions"][0]["step"], 4)

    def test_water_heater_redirect_keeps_target_range(self):
        result = self._convert([{
            "entity": "water_heater",
            "dps": [
                {"id": 2, "name": "current_temperature", "type": "integer"},
                {"id": 8, "name": "temperature", "type": "integer", "range": {"min": 0, "max": 100}, "mapping": [{"constraint": "temperature_unit", "conditions": [{"dps_val": "f", "value_redirect": "temp_f", "range": {"min": 32, "max": 212}}]}]},
                {"id": 9, "name": "temp_f", "type": "integer", "hidden": True, "range": {"min": 32, "max": 212}},
                {"id": 12, "name": "temperature_unit", "type": "string", "mapping": [{"dps_val": "c", "value": "°C"}, {"dps_val": "f", "value": "°F"}]},
            ],
        }])
        config = result["entities"][0]["config"]
        self.assertEqual(config["advanced_mapping_by_dp"]["9"], [{"range": {"min": 32, "max": 212}}])
        self.assertEqual(config["advanced_mapping_by_dp"]["8"][0]["conditions"][0]["range"], {"min": 32, "max": 212})

    def test_redirect_simple_target_scale_uses_ratio_and_target_step(self):
        result = self._convert([{
            "entity": "number",
            "dps": [
                {"id": 1, "name": "value", "type": "integer", "range": {"min": 70, "max": 300}, "mapping": [{"scale": 10, "step": 5, "constraint": "mode", "conditions": [{"dps_val": "boost", "value_redirect": "target"}]}]},
                {"id": 2, "name": "mode", "type": "string", "hidden": True},
                {"id": 3, "name": "target", "type": "integer", "hidden": True, "range": {"min": 300, "max": 700}, "mapping": [{"scale": 10, "step": 5}]},
            ],
        }])
        config = result["entities"][0]["config"]
        self.assertEqual(config["advanced_mapping_by_dp"]["3"], [{"step": 5.0, "range": {"min": 300, "max": 700}}])
        self.assertNotIn("scale", config["advanced_mapping_by_dp"]["3"][0])


if __name__ == "__main__":
    unittest.main()
