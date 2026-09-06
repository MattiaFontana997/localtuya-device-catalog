from pathlib import Path

path = Path('tools/import_tuya_local_productless.py')
text = path.read_text()
old = '''_FAN_EXTENDED_REASONS = {
    "fan_speed_percentages",
    "fan_speed_mapping",
    "fan_oscillate_mapping",
    "fan_preset_type",
    "fan_preset_optional",
}
'''
new = '''_FAN_EXTENDED_REASONS = {
    "fan_speed_percentages",
    "fan_speed_mapping",
    "fan_oscillate_mapping",
    "fan_preset_type",
    "fan_preset_optional",
    "fan_preset_hidden",
    "fan_missing_switch",
}
'''
if text.count(old) != 1:
    raise SystemExit(f'fan extended reasons anchor count={text.count(old)}')
text = text.replace(old, new, 1)
old = '''def _fan_productless_presets(dp: dict[str, Any], config: dict[str, Any]) -> None:
    try:
        values = base._fan_static_presets(dp)
    except ConversionError as err:
        if str(err) not in {"fan_preset_type", "fan_preset_optional"}:
            raise
    else:
        config["fan_preset_dp"] = base._dp_id(dp)
        config["fan_preset_values"] = values
        return

    base._check_common_dp_semantics(dp, writable=True)
    raw_type = base._dp_type(dp)
    if raw_type not in {"string", "integer", "boolean"}:
        raise ConversionError("fan_preset_type")
    values: dict[str, Any] = {}
    raw_seen: list[Any] = []
    for rule in _raw_mapping(dp):
        if set(rule) - {"dps_val", "value", "hidden"}:
            raise ConversionError("fan_preset_mapping")
        if rule.get("hidden") is True or "dps_val" not in rule or "value" not in rule:
            raise ConversionError("fan_preset_mapping")
        friendly = rule["value"]
        if not isinstance(friendly, str) or not friendly.strip():
            raise ConversionError("fan_preset_mapping")
        try:
            raw = coerce_fan_raw(rule["dps_val"], raw_type)
        except ValueError as err:
            raise ConversionError("fan_preset_mapping") from err
        friendly = friendly.strip()
        if friendly in values or any(raw == previous for previous in raw_seen):
            raise ConversionError("fan_preset_duplicate")
        values[friendly] = raw
        raw_seen.append(raw)
    if not values:
        raise ConversionError("fan_preset_mapping")
    config["fan_preset_dp"] = base._dp_id(dp)
    config["fan_preset_values"] = values
    config["fan_preset_raw_type"] = raw_type
'''
new = '''def _fan_productless_presets(dp: dict[str, Any], config: dict[str, Any]) -> None:
    try:
        values = base._fan_static_presets(dp)
    except ConversionError as err:
        if str(err) not in {"fan_preset_type", "fan_preset_optional", "fan_preset_hidden"}:
            raise
    else:
        config["fan_preset_dp"] = base._dp_id(dp)
        config["fan_preset_values"] = values
        return

    base._check_common_dp_semantics(dp, writable=True)
    raw_type = base._dp_type(dp)
    if raw_type not in {"string", "integer", "boolean"}:
        raise ConversionError("fan_preset_type")
    values: dict[str, Any] = {}
    raw_seen: list[Any] = []
    default_friendly: str | None = None
    for rule in _raw_mapping(dp):
        if set(rule) - {"dps_val", "value", "hidden"}:
            raise ConversionError("fan_preset_mapping")
        if rule.get("hidden") is True:
            # Tuya Local permits a hidden default rule without dps_val. It is
            # read-only fallback semantics: any unmatched raw value reports the
            # declared friendly preset, while writes still use a visible exact
            # rule for that friendly preset.
            if "dps_val" in rule or "value" not in rule or default_friendly is not None:
                raise ConversionError("fan_preset_mapping")
            friendly = rule["value"]
            if not isinstance(friendly, str) or not friendly.strip():
                raise ConversionError("fan_preset_mapping")
            default_friendly = friendly.strip()
            continue
        if "dps_val" not in rule or "value" not in rule:
            raise ConversionError("fan_preset_mapping")
        friendly = rule["value"]
        if not isinstance(friendly, str) or not friendly.strip():
            raise ConversionError("fan_preset_mapping")
        try:
            raw = coerce_fan_raw(rule["dps_val"], raw_type)
        except ValueError as err:
            raise ConversionError("fan_preset_mapping") from err
        friendly = friendly.strip()
        if friendly in values or any(raw == previous for previous in raw_seen):
            raise ConversionError("fan_preset_duplicate")
        values[friendly] = raw
        raw_seen.append(raw)
    if not values:
        raise ConversionError("fan_preset_mapping")
    if default_friendly is not None and default_friendly not in values:
        raise ConversionError("fan_preset_default_without_writable_value")
    config["fan_preset_dp"] = base._dp_id(dp)
    config["fan_preset_values"] = values
    config["fan_preset_raw_type"] = raw_type
    if default_friendly is not None:
        config["fan_preset_default"] = default_friendly
'''
if text.count(old) != 1:
    raise SystemExit(f'fan presets function anchor count={text.count(old)}')
text = text.replace(old, new, 1)
old = '''    dps = _fan_productless_dps(entity)
    switch = dps.get("switch")
    if switch is None:
        raise ConversionError("fan_missing_switch")
    base._check_common_dp_semantics(switch, writable=True)
    if base._dp_type(switch) != "boolean":
        raise ConversionError("fan_switch_type")
    base._identity_boolean_mapping(switch, "fan_switch_mapping")

    config: dict[str, Any] = {"id": base._dp_id(switch), "platform": "fan"}
    required: set[int] = set()
    optional: set[int] = set()
    base._merge_membership(required, optional, switch)

    speed = dps.get("speed")
'''
new = '''    dps = _fan_productless_dps(entity)
    switch = dps.get("switch")
    speed = dps.get("speed")
    if switch is None:
        if speed is None:
            raise ConversionError("fan_missing_switch")
        config: dict[str, Any] = {
            "id": base._dp_id(speed),
            "platform": "fan",
            "fan_no_switch": True,
        }
        required: set[int] = set()
        optional: set[int] = set()
    else:
        base._check_common_dp_semantics(switch, writable=True)
        if base._dp_type(switch) != "boolean":
            raise ConversionError("fan_switch_type")
        base._identity_boolean_mapping(switch, "fan_switch_mapping")
        config = {"id": base._dp_id(switch), "platform": "fan"}
        required = set()
        optional = set()
        base._merge_membership(required, optional, switch)

'''
if text.count(old) != 1:
    raise SystemExit(f'fan switch block anchor count={text.count(old)}')
text = text.replace(old, new, 1)
path.write_text(text)

Path('tests/test_productless_fan_residual.py').write_text('''"""Residual productless fan converter regressions."""\n\nimport sys\nimport unittest\nfrom pathlib import Path\n\nsys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))\n\nimport import_tuya_local as base\nimport import_tuya_local_productless as productless\n\nconvert_fan = productless.base._CONVERTERS["fan"]\n\n\nclass ProductlessFanResidualTests(unittest.TestCase):\n    def test_speed_only_fan_is_explicitly_no_switch(self):\n        entity = {"entity": "fan", "name": "Supply", "dps": [{\n            "id": 102, "type": "string", "name": "speed",\n            "mapping": [\n                {"dps_val": "0", "value": 10},\n                {"dps_val": "1", "value": 20},\n                {"dps_val": "9", "value": 100},\n            ],\n        }]}\n        converted, required, optional = convert_fan(entity)\n        cfg = converted["config"]\n        self.assertIs(cfg["fan_no_switch"], True)\n        self.assertEqual(cfg["id"], 102)\n        self.assertEqual(cfg["fan_speed_control"], 102)\n        self.assertEqual(required, {102})\n        self.assertEqual(optional, set())\n\n    def test_hidden_preset_default_is_read_fallback_only(self):\n        entity = {"entity": "fan", "dps": [\n            {"id": 1, "type": "boolean", "name": "switch"},\n            {"id": 3, "type": "string", "name": "preset_mode", "mapping": [\n                {"dps_val": "Auto", "value": "auto"},\n                {"dps_val": "4", "value": "manual"},\n                {"value": "manual", "hidden": True},\n            ]},\n        ]}\n        converted, required, optional = convert_fan(entity)\n        cfg = converted["config"]\n        self.assertEqual(cfg["fan_preset_values"], {"auto": "Auto", "manual": "4"})\n        self.assertEqual(cfg["fan_preset_default"], "manual")\n        self.assertEqual(required, {1, 3})\n        self.assertEqual(optional, set())\n\n    def test_hidden_exact_preset_stays_fail_closed(self):\n        entity = {"entity": "fan", "dps": [\n            {"id": 1, "type": "boolean", "name": "switch"},\n            {"id": 3, "type": "string", "name": "preset_mode", "mapping": [\n                {"dps_val": "Auto", "value": "auto"},\n                {"dps_val": "X", "value": "manual", "hidden": True},\n            ]},\n        ]}\n        with self.assertRaisesRegex(base.ConversionError, "fan_preset_mapping"):\n            convert_fan(entity)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''')
