"""Batch N mapped extra-state attribute importer tests."""

import unittest

import import_tuya_local_productless as productless


class ProductlessMappedExtraTests(unittest.TestCase):
    def test_climate_scaled_extra_is_mapped_and_removed_from_base_input(self):
        entity = {
            "entity": "climate",
            "dps": [
                {"id": 1, "name": "hvac_mode", "type": "boolean"},
                {
                    "id": 108, "name": "temperature_step", "type": "integer",
                    "readonly": True, "mapping": [{"scale": 10}],
                },
            ],
        }
        prepared, mapped = productless._prepare_complex_mapped_extras(entity, "climate")
        self.assertEqual([dp["name"] for dp in prepared["dps"]], ["hvac_mode"])
        self.assertEqual(mapped[0][0]["id"], 108)
        self.assertEqual(mapped[0][1], [{"scale": 10.0}])

    def test_simple_static_extra_uses_mapped_attribute_channel(self):
        advanced = {}
        config = {}
        required, optional = set(), set()
        dp = {
            "id": 23, "name": "unit", "type": "string", "readonly": True,
            "mapping": [
                {"dps_val": "c", "value": "C"},
                {"dps_val": "f", "value": "F"},
            ],
        }
        productless._preserve_simple_multi_dp_extras(
            "number", [dp], advanced, config, required, optional
        )
        self.assertEqual(config["mapped_extra_state_attributes_dps"], {"unit": 23})
        self.assertNotIn("extra_state_attributes_dps", config)
        self.assertEqual(config["mapped_extra_state_attribute_mappings"]["unit"], [
            {"dps_val": "c", "value": "C"},
            {"dps_val": "f", "value": "F"},
        ])
        self.assertEqual(advanced, {})
        self.assertIn(23, required)

    def test_raw_extra_behavior_is_unchanged(self):
        advanced = {}
        config = {}
        required, optional = set(), set()
        dp = {"id": 24, "name": "raw_info", "type": "string", "readonly": True}
        productless._preserve_simple_multi_dp_extras(
            "sensor", [dp], advanced, config, required, optional
        )
        self.assertEqual(config["extra_state_attributes_dps"], {"raw_info": 24})
        self.assertNotIn("mapped_extra_state_attributes_dps", config)
        self.assertEqual(advanced, {})

    def test_null_static_rule_remains_fail_closed(self):
        dp = {
            "id": 25, "name": "unit", "type": "string",
            "mapping": [{"dps_val": None, "value": "unknown"}],
        }
        with self.assertRaises(productless.ConversionError):
            productless._mapped_extra_runtime_rules(dp, "number", "unit")

    def test_richer_mapping_remains_fail_closed(self):
        dp = {
            "id": 26, "name": "unit", "type": "integer",
            "mapping": [{"scale": 10, "step": 1}],
        }
        with self.assertRaises(productless.ConversionError):
            productless._mapped_extra_runtime_rules(dp, "number", "unit")


if __name__ == "__main__":
    unittest.main()
