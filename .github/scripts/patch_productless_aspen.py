from pathlib import Path

path = Path("tools/import_tuya_local_productless.py")
text = path.read_text()

old = '''_FAN_EXTENDED_REASONS = {
    "fan_speed_percentages",
    "fan_speed_mapping",
    "fan_oscillate_mapping",
    "fan_preset_type",
    "fan_preset_optional",
    "fan_preset_hidden",
    "fan_missing_switch",
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
    "fan_direction_mapping",
}
'''
assert text.count(old) == 1
text = text.replace(old, new, 1)

marker = 'def _convert_fan_productless(entity: dict[str, Any]) -> base.Converted:\n'
assert text.count(marker) == 1
helper = '''def _fan_productless_direction(dp: dict[str, Any], config: dict[str, Any]) -> None:
    """Preserve Aspen's exact three-way fan direction mapping."""
    try:
        base._fan_direction_config(dp, config)
        return
    except ConversionError as err:
        if str(err) != "fan_direction_mapping":
            raise

    base._check_common_dp_semantics(dp, writable=True)
    if base._dp_type(dp) != "string":
        raise ConversionError("fan_direction_mapping")
    rules = _raw_mapping(dp)
    if len(rules) != 3:
        raise ConversionError("fan_direction_mapping")
    values: dict[str, str] = {}
    seen_raw: set[str] = set()
    for rule in rules:
        if set(rule) != {"dps_val", "value"}:
            raise ConversionError("fan_direction_mapping")
        raw = rule.get("dps_val")
        friendly = rule.get("value")
        if (
            not isinstance(raw, str)
            or not raw
            or not isinstance(friendly, str)
            or friendly not in {"forward", "reverse", "exchange"}
            or raw in seen_raw
            or friendly in values
        ):
            raise ConversionError("fan_direction_mapping")
        values[friendly] = raw
        seen_raw.add(raw)
    if set(values) != {"forward", "reverse", "exchange"}:
        raise ConversionError("fan_direction_mapping")
    config["fan_direction"] = base._dp_id(dp)
    config["fan_direction_values"] = values


'''
text = text.replace(marker, helper + marker, 1)

old = '''    direction = dps.get("direction")
    if direction is not None:
        base._fan_direction_config(direction, config)
        base._merge_membership(required, optional, direction)
'''
new = '''    direction = dps.get("direction")
    if direction is not None:
        _fan_productless_direction(direction, config)
        base._merge_membership(required, optional, direction)
'''
assert text.count(old) == 1
text = text.replace(old, new, 1)

marker = '''# Extend only the productless conversion surface. Keep the mature product-ID
# importer unchanged while wrapping its converters for Batch F on this module's
# develop-only path.
'''
assert text.count(marker) == 1
light_helper = '''def _convert_light_productless(
    entity: dict[str, Any],
    *,
    scene_dp: dict[str, Any] | None = None,
    scene_values: dict[str, str] | None = None,
) -> base.Converted:
    """Extend productless lights with exact brightness-as-power integer DPS."""
    if _PRODUCTLESS_BASE_LIGHT is None:
        raise ConversionError("light_missing_switch")
    try:
        return _PRODUCTLESS_BASE_LIGHT(
            entity, scene_dp=scene_dp, scene_values=scene_values
        )
    except ConversionError as err:
        if str(err) != "light_missing_switch":
            raise

    if scene_dp is not None or scene_values:
        raise ConversionError("light_missing_switch")
    if entity.get("class") is not None:
        raise ConversionError("light_device_class")
    base._entity_metadata(entity, {})
    dps = base._light_dps(entity)
    if set(dps) != {"brightness"}:
        raise ConversionError("light_missing_switch")
    brightness = dps["brightness"]
    base._check_common_dp_semantics(brightness, writable=True)
    if base._dp_type(brightness) != "integer":
        raise ConversionError("light_missing_switch")
    if _raw_mapping(brightness):
        raise ConversionError("light_brightness_power_mapping")
    if brightness.get("step") not in (None, 1):
        raise ConversionError("light_brightness_step")
    minimum, maximum = base._raw_integer_range(brightness, "light_brightness")
    if minimum <= 0 or maximum <= minimum:
        raise ConversionError("light_missing_switch")
    allowed = {
        "id", "type", "name", "optional", "readonly", "hidden", "force",
        "persist", "sensitive", "range", "step", "unit", "class", "category",
    }
    if set(brightness) - allowed:
        raise ConversionError("light_brightness_power_semantics")
    config: dict[str, Any] = {
        "id": base._dp_id(brightness),
        "platform": "light",
        "music_mode": False,
        "brightness": base._dp_id(brightness),
        "brightness_lower": minimum,
        "brightness_upper": maximum,
        "brightness_as_power": True,
        "brightness_power_off_value": 0,
    }
    required: set[int] = set()
    optional: set[int] = set()
    base._merge_membership(required, optional, brightness)
    return {"platform": "light", "config": config}, required, optional


'''
text = text.replace(marker, light_helper + marker, 1)

old = '_original_converters = dict(base._CONVERTERS)\n'
new = '_original_converters = dict(base._CONVERTERS)\n_PRODUCTLESS_BASE_LIGHT = _original_converters.get("light")\n'
assert text.count(old) == 1
text = text.replace(old, new, 1)

old = '_original_converters["fan"] = _convert_fan_productless\n'
new = old + '_original_converters["light"] = _convert_light_productless\n'
assert text.count(old) == 1
text = text.replace(old, new, 1)

old = '    base._convert_light = _advanced_wrapper("light", base._convert_light)\n'
new = '    base._convert_light = _advanced_wrapper("light", _convert_light_productless)\n'
assert text.count(old) == 1
text = text.replace(old, new, 1)

path.write_text(text)

# Focused regression tests.
path = Path("tests/test_import_tuya_local_productless.py")
text = path.read_text()
marker = '\n\nif __name__ == "__main__":\n    unittest.main()\n'
assert text.count(marker) == 1
cases = '''
    def test_aspen_three_way_fan_direction_is_exact(self):
        result = self._convert([
            {
                "entity": "fan",
                "dps": [
                    {"id": 1, "type": "boolean", "name": "switch"},
                    {"id": 2, "type": "string", "name": "direction", "mapping": [
                        {"dps_val": "in", "value": "forward"},
                        {"dps_val": "out", "value": "reverse"},
                        {"dps_val": "exch", "value": "exchange"},
                    ]},
                    {"id": 3, "type": "integer", "name": "speed", "range": {"min": 1, "max": 3}},
                ],
            }
        ])
        config = result["entities"][0]["config"]
        self.assertEqual(config["fan_direction"], 2)
        self.assertEqual(config["fan_direction_values"], {
            "forward": "in", "reverse": "out", "exchange": "exch"
        })

    def test_brightness_only_integer_light_preserves_zero_off(self):
        result = self._convert([
            {
                "entity": "light",
                "dps": [
                    {"id": 102, "type": "integer", "name": "brightness", "range": {"min": 1, "max": 3}},
                ],
            }
        ])
        config = result["entities"][0]["config"]
        self.assertEqual(config["id"], 102)
        self.assertEqual(config["brightness"], 102)
        self.assertTrue(config["brightness_as_power"])
        self.assertEqual(config["brightness_power_off_value"], 0)
        self.assertEqual((config["brightness_lower"], config["brightness_upper"]), (1, 3))

    def test_brightness_only_zero_based_range_stays_fail_closed(self):
        with self.assertRaisesRegex(ConversionError, "light_missing_switch"):
            self._convert([
                {
                    "entity": "light",
                    "dps": [
                        {"id": 102, "type": "integer", "name": "brightness", "range": {"min": 0, "max": 3}},
                    ],
                }
            ])
'''
text = text.replace(marker, cases + marker, 1)
path.write_text(text)
