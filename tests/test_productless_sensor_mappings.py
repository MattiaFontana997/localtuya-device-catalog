"""Batch J converter regressions for the real enum and numeric shapes."""

import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from import_tuya_local_productless import convert_profile, ConversionError
from sensor_mapping import evaluate_sensor_value_mapping


class ProductlessSensorMappingTests(unittest.TestCase):
    def convert(self, rules, raw_type="string"):
        return convert_profile({"name": "Sensor", "products": [{"id": "test"}], "entities": [{"entity": "sensor", "dps": [{"id": 1, "name": "sensor", "type": raw_type, "mapping": rules}]}]}, source_file="sensor.yaml")["entities"][0]["config"]

    def test_actual_battery_enum_values_are_numeric(self):
        config = self.convert([{"dps_val": "low", "value": 20}, {"dps_val": "middle", "value": 50}, {"dps_val": "high", "value": 80}])
        self.assertEqual(evaluate_sensor_value_mapping("middle", config["sensor_value_mapping"])[0], 50)

    def test_scale_has_no_legacy_precision_loss(self):
        config = self.convert([{"scale": 1000}], "integer")
        self.assertNotIn("scaling", config)
        self.assertEqual(evaluate_sensor_value_mapping(1234, config["sensor_value_mapping"])[0], 1.234)

    def test_real_null_and_icon_rules(self):
        rules = [{"dps_val": None, "value": "unchecked"}, {"dps_val": "ok", "value": "success"}]
        self.assertEqual(self.convert(rules)["sensor_value_mapping"]["rules"], rules)
        rules = [{"dps_val": "No_water", "value": 0, "icon": "mdi:cup-outline"}]
        self.assertEqual(self.convert(rules)["sensor_value_mapping"]["rules"], rules)

    def test_arbitrary_calculation_and_offset_remain_fail_closed(self):
        for rule in [{"expression": "x+1"}, {"offset": 2}, {"scale": float("nan")}]:
            with self.assertRaises(ConversionError):
                self.convert([rule], "integer")
