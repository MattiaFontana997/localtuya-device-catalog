"""Productless exact Switch raw-semantics regressions."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import import_tuya_local as base
import import_tuya_local_productless as productless


convert_switch = productless.base._CONVERTERS["switch"]


class ProductlessSwitchRawTests(unittest.TestCase):
    def test_inverted_boolean(self):
        entity = {"entity": "switch", "dps": [{"id": 101, "type": "boolean", "name": "switch", "mapping": [
            {"dps_val": True, "value": False}, {"dps_val": False, "value": True}
        ]}]}
        converted, required, optional = convert_switch(entity)
        self.assertIs(converted["config"]["switch_on_value"], False)
        self.assertIs(converted["config"]["switch_off_value"], True)
        self.assertEqual(required, {101})
        self.assertEqual(optional, set())

    def test_string_tokens(self):
        entity = {"entity": "switch", "dps": [{"id": 27, "type": "string", "name": "switch", "mapping": [
            {"dps_val": "online", "value": True}, {"dps_val": "offline", "value": False}
        ]}]}
        converted, _, _ = convert_switch(entity)
        self.assertEqual(converted["config"]["switch_on_value"], "online")
        self.assertEqual(converted["config"]["switch_off_value"], "offline")

    def test_icon_only_boolean_default(self):
        entity = {"entity": "switch", "dps": [{"id": 110, "type": "boolean", "name": "switch", "mapping": [
            {"dps_val": True, "icon": "mdi:microphone"}, {"icon": "mdi:microphone-off"}
        ]}]}
        converted, _, _ = convert_switch(entity)
        cfg = converted["config"]
        self.assertIs(cfg["switch_on_value"], True)
        self.assertIs(cfg["switch_off_value"], False)
        self.assertEqual(cfg["switch_icon_on"], "mdi:microphone")
        self.assertEqual(cfg["switch_icon_off"], "mdi:microphone-off")

    def test_hex_one_bit_mask(self):
        entity = {"entity": "switch", "dps": [{"id": 123, "type": "hex", "name": "switch", "mask": "0010"}]}
        converted, required, _ = convert_switch(entity)
        self.assertEqual(converted["config"]["switch_mask"], "0010")
        self.assertEqual(required, {123})

    def test_multi_bit_mask_stays_fail_closed(self):
        entity = {"entity": "switch", "dps": [{"id": 123, "type": "hex", "name": "switch", "mask": "0030"}]}
        with self.assertRaisesRegex(base.ConversionError, "switch_mask"):
            convert_switch(entity)


if __name__ == "__main__":
    unittest.main()
