from pathlib import Path

path = Path('tools/import_tuya_local_productless.py')
text = path.read_text()
helper = r'''
def _switch_mapping_state_icons(
    dp: dict[str, Any], raw_type: str
) -> tuple[Any, Any, str | None, str | None]:
    rules = _raw_mapping(dp)
    if not rules:
        raise ConversionError("switch_mapping")
    explicit: list[tuple[Any, bool, str | None]] = []
    default_rule: dict[str, Any] | None = None
    for rule in rules:
        if set(rule) - {"dps_val", "value", "icon", "hidden"}:
            raise ConversionError("switch_mapping_semantics")
        if rule.get("hidden") is True:
            raise ConversionError("switch_mapping_semantics")
        icon = rule.get("icon")
        if icon is not None and (not isinstance(icon, str) or not icon.strip()):
            raise ConversionError("switch_mapping_icon")
        if "dps_val" not in rule:
            if default_rule is not None:
                raise ConversionError("switch_mapping_multiple_defaults")
            default_rule = rule
            continue
        raw = rule["dps_val"]
        if raw_type == "boolean":
            if not isinstance(raw, bool):
                raise ConversionError("switch_mapping_raw_type")
            friendly = rule.get("value", raw)
        elif raw_type == "string":
            if not isinstance(raw, str) or "value" not in rule:
                raise ConversionError("switch_mapping_raw_type")
            friendly = rule["value"]
        elif raw_type == "integer":
            if isinstance(raw, bool) or not isinstance(raw, int) or "value" not in rule:
                raise ConversionError("switch_mapping_raw_type")
            friendly = rule["value"]
        else:
            raise ConversionError("switch_non_boolean")
        if not isinstance(friendly, bool):
            raise ConversionError("switch_mapping_non_boolean")
        explicit.append((raw, friendly, icon.strip() if isinstance(icon, str) else None))

    if raw_type == "boolean":
        by_raw = {raw: (friendly, icon) for raw, friendly, icon in explicit}
        for raw in (False, True):
            if raw not in by_raw:
                if default_rule is None:
                    raise ConversionError("switch_mapping_incomplete")
                friendly = default_rule.get("value", raw)
                if not isinstance(friendly, bool):
                    raise ConversionError("switch_mapping_non_boolean")
                icon = default_rule.get("icon")
                by_raw[raw] = (friendly, icon.strip() if isinstance(icon, str) else None)
        entries = [(raw, *by_raw[raw]) for raw in (False, True)]
    else:
        if default_rule is not None or len(explicit) != 2:
            raise ConversionError("switch_mapping_incomplete")
        entries = [(raw, friendly, icon) for raw, friendly, icon in explicit]

    on = [(raw, icon) for raw, friendly, icon in entries if friendly is True]
    off = [(raw, icon) for raw, friendly, icon in entries if friendly is False]
    if len(on) != 1 or len(off) != 1:
        raise ConversionError("switch_mapping_ambiguous")
    return on[0][0], off[0][0], on[0][1], off[0][1]


def _convert_switch_productless(entity: dict[str, Any]) -> base.Converted:
    """Convert exact raw, inverted, icon-mapped and one-bit hex Switch DPS."""
    dp = base._single_named_dp(entity, "switch")
    raw_type = base._dp_type(dp)
    mask = dp.get("mask")
    mapping = _raw_mapping(dp)
    if mask is None and not mapping:
        return base._convert_switch(entity)

    if dp.get("readonly") is True or dp.get("sensitive") is True:
        raise ConversionError("switch_semantics")
    allowed = {
        "id", "type", "name", "optional", "readonly", "hidden", "force",
        "persist", "sensitive", "mapping", "mask", "endianness",
    }
    if set(dp) - allowed:
        raise ConversionError("switch_semantics")

    config: dict[str, Any] = {"id": base._dp_id(dp), "platform": "switch"}
    base._entity_metadata(entity, config)
    if mask is not None:
        if mapping or raw_type != "hex" or not isinstance(mask, str) or not mask or len(mask) % 2:
            raise ConversionError("switch_mask")
        try:
            mask_value = int(mask, 16)
        except ValueError as err:
            raise ConversionError("switch_mask") from err
        if mask_value <= 0 or mask_value & (mask_value - 1):
            raise ConversionError("switch_mask")
        endianness = dp.get("endianness", "big")
        if endianness not in {"big", "little"}:
            raise ConversionError("switch_mask_endianness")
        config["switch_mask"] = mask
        if endianness != "big":
            config["switch_mask_endianness"] = endianness
    else:
        if raw_type not in {"boolean", "string", "integer"}:
            raise ConversionError("switch_non_boolean")
        raw_on, raw_off, icon_on, icon_off = _switch_mapping_state_icons(dp, raw_type)
        config["switch_on_value"] = raw_on
        config["switch_off_value"] = raw_off
        if icon_on is not None:
            config["switch_icon_on"] = icon_on
        if icon_off is not None:
            config["switch_icon_off"] = icon_off

    required: set[int] = set()
    optional: set[int] = set()
    base._merge_membership(required, optional, dp)
    return {"platform": "switch", "config": config}, required, optional


'''
anchor = '_FAN_EXTENDED_REASONS = {'
if text.count(anchor) != 1:
    raise SystemExit(f'switch insertion anchor count={text.count(anchor)}')
text = text.replace(anchor, helper + anchor, 1)
old = '''_original_converters["sensor"] = _convert_sensor_productless
_original_converters["fan"] = _convert_fan_productless
'''
new = '''_original_converters["sensor"] = _convert_sensor_productless
_original_converters["switch"] = _convert_switch_productless
_original_converters["fan"] = _convert_fan_productless
'''
if text.count(old) != 1:
    raise SystemExit(f'switch registry anchor count={text.count(old)}')
path.write_text(text.replace(old, new, 1))

Path('tests/test_productless_switch_raw.py').write_text(r'''"""Productless exact Switch raw-semantics regressions."""

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
''')
