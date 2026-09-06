"""Productless Select device-class metadata regressions."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import import_tuya_local as base
import import_tuya_local_productless as productless

convert_select = productless._advanced_wrapper("select", base._convert_select)


class ProductlessSelectDeviceClassTests(unittest.TestCase):
    def test_duration_class_with_translation_key_is_metadata_only(self):
        entity = {
            "entity": "select",
            "translation_key": "timer",
            "class": "duration",
            "category": "config",
            "dps": [{
                "id": 19,
                "type": "string",
                "name": "option",
                "mapping": [
                    {"dps_val": "0h", "value": "cancel"},
                    {"dps_val": "1h", "value": "1h"},
                    {"dps_val": "24h", "value": "24h"},
                ],
            }],
        }
        converted, required, optional = convert_select(entity)
        self.assertEqual(converted["config"]["options"], "0h;1h;24h")
        self.assertEqual(converted["config"]["options_friendly"], "cancel;1h;24h")
        self.assertNotIn("device_class", converted["config"])
        self.assertEqual(required, {19})
        self.assertEqual(optional, set())

    def test_other_select_class_remains_fail_closed(self):
        entity = {
            "entity": "select",
            "translation_key": "timer",
            "class": "mode",
            "dps": [{
                "id": 1,
                "type": "string",
                "name": "option",
                "mapping": [{"dps_val": "a", "value": "a"}],
            }],
        }
        with self.assertRaisesRegex(base.ConversionError, "select_device_class"):
            convert_select(entity)

    def test_unnamed_duration_select_remains_fail_closed(self):
        entity = {
            "entity": "select",
            "class": "duration",
            "dps": [{
                "id": 1,
                "type": "string",
                "name": "option",
                "mapping": [{"dps_val": "a", "value": "a"}],
            }],
        }
        with self.assertRaisesRegex(base.ConversionError, "select_device_class"):
            convert_select(entity)


if __name__ == "__main__":
    unittest.main()
