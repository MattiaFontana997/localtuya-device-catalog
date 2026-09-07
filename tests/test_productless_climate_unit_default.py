"""Productless Climate default temperature-unit mapping regressions."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import import_tuya_local as base
import import_tuya_local_productless as productless

convert_climate = productless.base._CONVERTERS["climate"]


class ClimateUnitDefaultTests(unittest.TestCase):
    def test_f_explicit_c_default_becomes_exact_runtime_unit_map(self):
        entity = {"entity": "climate", "dps": [
            {"id": 1, "type": "boolean", "name": "hvac_mode", "mapping": [
                {"dps_val": False, "value": "off"}, {"dps_val": True, "value": "heat"}
            ]},
            {"id": 13, "type": "string", "name": "temperature_unit", "mapping": [
                {"dps_val": "f", "value": "F"}, {"value": "C"}
            ]},
        ]}
        converted, required, optional = convert_climate(entity)
        cfg = converted["config"]
        self.assertEqual(cfg["temperature_unit_values"], {"fahrenheit": "f", "celsius": "C"})
        self.assertEqual(required, {1, 13})
        self.assertEqual(optional, set())

    def test_non_unit_default_shape_stays_fail_closed(self):
        entity = {"entity": "climate", "dps": [
            {"id": 1, "type": "boolean", "name": "hvac_mode", "mapping": [
                {"dps_val": False, "value": "off"}, {"dps_val": True, "value": "heat"}
            ]},
            {"id": 13, "type": "string", "name": "temperature_unit", "mapping": [
                {"dps_val": "x", "value": "F"}, {"value": "C", "hidden": True}
            ]},
        ]}
        with self.assertRaisesRegex(base.ConversionError, "climate_temperature_unit_mapping"):
            convert_climate(entity)


if __name__ == "__main__":
    unittest.main()
