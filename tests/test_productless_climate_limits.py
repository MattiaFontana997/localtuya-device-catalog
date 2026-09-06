"""Batch N productless Climate scaled limit tests."""

import unittest

import import_tuya_local_productless as productless


class ProductlessClimateLimitTests(unittest.TestCase):
    def test_scaled_min_max_are_projected_to_independent_precision(self):
        entity = {
            "entity": "climate",
            "dps": [
                {"id": 26, "name": "min_temperature", "type": "integer", "mapping": [{"scale": 10}]},
                {"id": 19, "name": "max_temperature", "type": "integer", "mapping": [{"scale": 10}]},
            ],
        }
        transformed, precision = productless._prepare_climate_limit_precisions(entity)
        self.assertEqual(precision, {
            "min_temperature_precision": 0.1,
            "max_temperature_precision": 0.1,
        })
        self.assertNotIn("mapping", transformed["dps"][0])
        self.assertNotIn("mapping", transformed["dps"][1])
        self.assertIn("mapping", entity["dps"][0])

    def test_richer_limit_mapping_remains_for_fail_closed_base_converter(self):
        entity = {
            "entity": "climate",
            "dps": [{
                "id": 26, "name": "min_temperature", "type": "integer",
                "mapping": [{"scale": 10, "step": 5}],
            }],
        }
        transformed, precision = productless._prepare_climate_limit_precisions(entity)
        self.assertEqual(precision, {})
        self.assertEqual(transformed["dps"][0]["mapping"], [{"scale": 10, "step": 5}])

    def test_invalid_scale_is_not_consumed(self):
        entity = {
            "entity": "climate",
            "dps": [{
                "id": 26, "name": "min_temperature", "type": "integer",
                "mapping": [{"scale": 0}],
            }],
        }
        transformed, precision = productless._prepare_climate_limit_precisions(entity)
        self.assertEqual(precision, {})
        self.assertIn("mapping", transformed["dps"][0])


if __name__ == "__main__":
    unittest.main()
