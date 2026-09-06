from pathlib import Path

path = Path('tools/import_tuya_local_productless.py')
text = path.read_text(encoding='utf-8')

old = '''    enum_names = {\n        "climate": {\n            "hvac_mode", "preset_mode", "fan_mode", "swing_mode",\n            "swing_horizontal_mode", "hvac_action", "temperature_unit",\n        },\n    }'''
new = '''    enum_names = {\n        "climate": {\n            "hvac_mode", "preset_mode", "fan_mode", "swing_mode",\n            "swing_horizontal_mode", "hvac_action", "temperature_unit",\n        },\n        "water_heater": {"operation_mode", "temperature_unit"},\n    }'''
if old not in text:
    raise SystemExit('advanced projection enum marker missing')
text = text.replace(old, new, 1)

old = '''    projected["mapping"] = [\n        {"dps_val": value, "value": value} for value in outputs\n    ]\n    return projected'''
new = '''    projected["mapping"] = [\n        {"dps_val": value, "value": value} for value in outputs\n    ]\n    if platform == "water_heater" and name == "operation_mode":\n        projected["_productless_source_type"] = base._dp_type(dp)\n    return projected'''
if old not in text:
    raise SystemExit('advanced projection return marker missing')
text = text.replace(old, new, 1)

marker = '\n\ndef _convert_binary_sensor_productless('
insert = r'''


def _water_heater_raw_matches_type(value: Any, raw_type: str) -> bool:
    if raw_type == "boolean":
        return isinstance(value, bool)
    if raw_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if raw_type == "string":
        return isinstance(value, str)
    return False


def _water_heater_mode_values(dp: dict[str, Any]) -> tuple[dict[str, Any], str]:
    base._check_common_dp_semantics(dp, writable=True)
    raw_type = base._dp_type(dp)
    source_type = dp.get("_productless_source_type", raw_type)
    if source_type not in {"boolean", "integer", "string"}:
        raise ConversionError("water_heater_operation_mode_type")
    if raw_type not in {"boolean", "integer", "string"}:
        raise ConversionError("water_heater_operation_mode_type")
    rules = base._mapping_rules(dp)
    if not rules:
        if raw_type == "boolean":
            return {"off": False, "on": True}, source_type
        raise ConversionError("water_heater_operation_mode_mapping")
    values: dict[str, Any] = {}
    seen_raw: list[Any] = []
    for rule in rules:
        if set(rule) != {"dps_val", "value"}:
            raise ConversionError("water_heater_operation_mode_mapping")
        raw = rule["dps_val"]
        friendly = rule["value"]
        if not _water_heater_raw_matches_type(raw, raw_type):
            raise ConversionError("water_heater_operation_mode_mapping")
        if not isinstance(friendly, str) or not friendly.strip():
            raise ConversionError("water_heater_operation_mode_mapping")
        friendly = friendly.strip()
        if friendly in values or any(raw == previous and type(raw) is type(previous) for previous in seen_raw):
            raise ConversionError("water_heater_operation_mode_duplicate")
        values[friendly] = raw
        seen_raw.append(raw)
    return values, source_type


def _water_heater_numeric(
    dp: dict[str, Any], *, writable: bool, require_range: bool, reason: str
) -> tuple[float, dict[str, Any] | None, float]:
    base._check_common_dp_semantics(dp, writable=writable)
    if base._dp_type(dp) != "integer":
        raise ConversionError(f"{reason}_type")
    precision = dp.get("precision")
    if precision not in (None, 0):
        raise ConversionError(f"{reason}_precision")
    if writable:
        scaling, rule = base._numeric_rule(dp)
    else:
        scaling = base._default_scale_rule(dp)
        rule = {}
    range_config = rule.get("range", dp.get("range"))
    if require_range and not isinstance(range_config, dict):
        raise ConversionError(f"{reason}_range")
    if range_config is not None:
        if not isinstance(range_config, dict) or "min" not in range_config or "max" not in range_config:
            raise ConversionError(f"{reason}_range")
        minimum = base._range_value(range_config["min"], scaling, f"{reason}_range")
        maximum = base._range_value(range_config["max"], scaling, f"{reason}_range")
        if maximum < minimum:
            raise ConversionError(f"{reason}_range")
    raw_step = rule.get("step", dp.get("step", 1))
    step = base._range_value(raw_step, scaling, f"{reason}_step")
    if step <= 0:
        raise ConversionError(f"{reason}_step")
    return scaling, range_config, step


def _water_heater_unit(value: Any) -> str:
    if value in {"C", "°C"}:
        return "°C"
    if value in {"F", "°F"}:
        return "°F"
    raise ConversionError("water_heater_temperature_unit")


def _water_heater_temperature_unit_values(dp: dict[str, Any]) -> dict[str, Any]:
    base._check_common_dp_semantics(dp, writable=True)
    raw_type = base._dp_type(dp)
    if raw_type not in {"string", "integer"}:
        raise ConversionError("water_heater_temperature_unit_type")
    rules = base._mapping_rules(dp)
    if not rules:
        raise ConversionError("water_heater_temperature_unit_mapping")
    values: dict[str, Any] = {}
    seen_raw: list[Any] = []
    for rule in rules:
        if set(rule) != {"dps_val", "value"}:
            raise ConversionError("water_heater_temperature_unit_mapping")
        raw = rule["dps_val"]
        if not _water_heater_raw_matches_type(raw, raw_type):
            raise ConversionError("water_heater_temperature_unit_mapping")
        friendly = _water_heater_unit(rule["value"])
        if friendly in values or any(raw == previous and type(raw) is type(previous) for previous in seen_raw):
            raise ConversionError("water_heater_temperature_unit_duplicate")
        values[friendly] = raw
        seen_raw.append(raw)
    return values


def _convert_water_heater_productless(entity: dict[str, Any]) -> base.Converted:
    """Convert lossless Tuya Local water-heater semantics for Catalog V3."""
    if entity.get("class") is not None:
        raise ConversionError("water_heater_device_class")
    base._entity_metadata(entity, {})
    dps = _named_dps(entity, "water_heater")
    primary = next(
        (dps[name] for name in ("operation_mode", "temperature", "current_temperature") if name in dps),
        None,
    )
    if primary is None:
        raise ConversionError("water_heater_missing_functional_dp")

    config: dict[str, Any] = {"id": base._dp_id(primary), "platform": "water_heater"}
    required: set[int] = set()
    optional: set[int] = set()
    consumed: set[str] = set()
    scales: list[float] = []
    static_units: set[str] = set()

    operation = dps.get("operation_mode")
    if operation is not None:
        mode_values, source_type = _water_heater_mode_values(operation)
        dp_id = base._dp_id(operation)
        config["water_heater_mode_dp"] = dp_id
        config["water_heater_mode_values"] = mode_values
        if source_type == "boolean":
            config["water_heater_power_dp"] = dp_id
            config["water_heater_power_on"] = True
            config["water_heater_power_off"] = False
        base._merge_membership(required, optional, operation)
        consumed.add("operation_mode")

    target = dps.get("temperature")
    if target is not None:
        scaling, range_config, step = _water_heater_numeric(
            target, writable=True, require_range=True, reason="water_heater_temperature"
        )
        scales.append(scaling)
        dp_id = base._dp_id(target)
        config["water_heater_target_temperature_dp"] = dp_id
        assert range_config is not None
        config["water_heater_temperature_min"] = base._range_value(
            range_config["min"], scaling, "water_heater_temperature_range"
        )
        config["water_heater_temperature_max"] = base._range_value(
            range_config["max"], scaling, "water_heater_temperature_range"
        )
        config["water_heater_temperature_step"] = step
        if target.get("unit") is not None:
            static_units.add(_water_heater_unit(target.get("unit")))
        base._merge_membership(required, optional, target)
        consumed.add("temperature")

    current = dps.get("current_temperature")
    if current is not None:
        scaling, _, _ = _water_heater_numeric(
            current, writable=False, require_range=False, reason="water_heater_current_temperature"
        )
        scales.append(scaling)
        config["water_heater_current_temperature_dp"] = base._dp_id(current)
        if current.get("unit") is not None:
            static_units.add(_water_heater_unit(current.get("unit")))
        base._merge_membership(required, optional, current)
        consumed.add("current_temperature")

    if scales:
        first = scales[0]
        if any(abs(scale - first) > 1e-12 for scale in scales[1:]):
            raise ConversionError("water_heater_temperature_scale_mismatch")
        if first != 1.0:
            config["water_heater_temperature_scaling"] = first

    unit_dp = dps.get("temperature_unit")
    if unit_dp is not None:
        config["water_heater_temperature_unit_dp"] = base._dp_id(unit_dp)
        config["water_heater_temperature_unit_values"] = _water_heater_temperature_unit_values(unit_dp)
        base._merge_membership(required, optional, unit_dp)
        consumed.add("temperature_unit")
    elif static_units:
        if len(static_units) != 1:
            raise ConversionError("water_heater_temperature_unit_mismatch")
        config["water_heater_temperature_unit"] = next(iter(static_units))

    for name, config_key in (
        ("min_temperature", "water_heater_min_temperature_dp"),
        ("max_temperature", "water_heater_max_temperature_dp"),
    ):
        dp = dps.get(name)
        if dp is None:
            continue
        scaling, _, _ = _water_heater_numeric(
            dp, writable=False, require_range=False, reason=f"water_heater_{name}"
        )
        if scales and abs(scaling - scales[0]) > 1e-12:
            raise ConversionError("water_heater_temperature_scale_mismatch")
        config[config_key] = base._dp_id(dp)
        base._merge_membership(required, optional, dp)
        consumed.add(name)

    away = dps.get("away_mode")
    if away is not None:
        base._check_common_dp_semantics(away, writable=True)
        if base._dp_type(away) != "boolean":
            raise ConversionError("water_heater_away_type")
        base._identity_boolean_mapping(away, "water_heater_away_mapping")
        config["water_heater_away_dp"] = base._dp_id(away)
        config["water_heater_away_on"] = True
        config["water_heater_away_off"] = False
        base._merge_membership(required, optional, away)
        consumed.add("away_mode")

    for name, dp in dps.items():
        if name in consumed:
            continue
        base._preserve_core_extra("water_heater", name, dp, config, required, optional)

    return {"platform": "water_heater", "config": config}, required, optional
'''
if marker not in text:
    raise SystemExit('water heater insertion marker missing')
text = text.replace(marker, insert + marker, 1)

old = 'base.SUPPORTED_PLATFORMS.update({"time", "event"})'
new = 'base.SUPPORTED_PLATFORMS.update({"time", "event", "water_heater"})'
if old not in text:
    raise SystemExit('supported platforms marker missing')
text = text.replace(old, new, 1)

old = '''_original_converters["sensor"] = _convert_sensor_productless\n_original_converters["fan"] = _convert_fan_productless'''
new = '''_original_converters["sensor"] = _convert_sensor_productless\n_original_converters["fan"] = _convert_fan_productless\n_original_converters["water_heater"] = _convert_water_heater_productless'''
if old not in text:
    raise SystemExit('water heater converter registration marker missing')
text = text.replace(old, new, 1)

path.write_text(text, encoding='utf-8')

test = Path('tests/test_productless_water_heater.py')
test.write_text('''"""Batch L productless water-heater importer tests."""\n\nimport unittest\n\nimport import_tuya_local as base\nimport import_tuya_local_productless as productless\n\n\nclass ProductlessWaterHeaterTests(unittest.TestCase):\n    def test_static_boolean_mode_temperature_away_and_extras_convert(self):\n        entity = {\n            "entity": "water_heater",\n            "dps": [\n                {"id": 1, "type": "boolean", "name": "operation_mode", "mapping": [\n                    {"dps_val": False, "value": "off"},\n                    {"dps_val": True, "value": "electric"},\n                ]},\n                {"id": 9, "type": "integer", "name": "temperature", "unit": "C", "range": {"min": 35, "max": 75}},\n                {"id": 13, "type": "string", "name": "work_mode"},\n                {"id": 20, "type": "integer", "name": "attr1"},\n                {"id": 101, "type": "boolean", "name": "away_mode"},\n                {"id": 102, "type": "integer", "name": "current_temperature"},\n            ],\n        }\n        converted, required, optional = productless._convert_water_heater_productless(entity)\n        config = converted["config"]\n        self.assertEqual(config["water_heater_mode_values"], {"off": False, "electric": True})\n        self.assertEqual(config["water_heater_power_dp"], 1)\n        self.assertEqual(config["water_heater_target_temperature_dp"], 9)\n        self.assertEqual(config["water_heater_current_temperature_dp"], 102)\n        self.assertEqual(config["water_heater_temperature_unit"], "°C")\n        self.assertEqual(config["water_heater_away_dp"], 101)\n        self.assertEqual(config["extra_state_attributes_dps"], {"work_mode": 13, "attr1": 20})\n        self.assertEqual(required, {1, 9, 13, 20, 101, 102})\n        self.assertEqual(optional, set())\n\n    def test_conditioned_boolean_mode_projects_to_logical_mode_domain(self):\n        entity = {\n            "entity": "water_heater",\n            "dps": [\n                {"id": 1, "type": "boolean", "name": "operation_mode", "mapping": [\n                    {"dps_val": False, "value": "off"},\n                    {"dps_val": True, "constraint": "work_mode", "conditions": [\n                        {"dps_val": "ECO", "value": "eco"},\n                        {"dps_val": "STANDARD", "value": "heat_pump"},\n                        {"dps_val": "ELEMENT", "value": "electric"},\n                    ]},\n                ]},\n                {"id": 2, "type": "integer", "name": "temperature", "unit": "C", "range": {"min": 15, "max": 75}},\n                {"id": 3, "type": "integer", "name": "current_temperature"},\n                {"id": 4, "type": "string", "name": "work_mode", "hidden": True},\n            ],\n        }\n        converted, required, optional = base._CONVERTERS["water_heater"](entity)\n        config = converted["config"]\n        self.assertEqual(config["water_heater_power_on"], True)\n        self.assertEqual(config["water_heater_power_off"], False)\n        self.assertEqual(\n            config["water_heater_mode_values"],\n            {"off": "off", "eco": "eco", "heat_pump": "heat_pump", "electric": "electric"},\n        )\n        self.assertIn("1", config["advanced_mapping_by_dp"])\n        self.assertEqual(required, {1, 2, 3, 4})\n        self.assertEqual(optional, set())\n        self.assertNotIn("work_mode", config.get("extra_state_attributes_dps", {}))\n\n    def test_dynamic_fahrenheit_range_remains_fail_closed(self):\n        entity = {\n            "entity": "water_heater",\n            "dps": [\n                {"id": 2, "type": "integer", "name": "current_temperature"},\n                {"id": 8, "type": "integer", "name": "temperature", "range": {"min": 0, "max": 100}, "mapping": [\n                    {"constraint": "temperature_unit", "conditions": [\n                        {"dps_val": "f", "value_redirect": "temp_set_f", "range": {"min": 32, "max": 212}},\n                    ]},\n                ]},\n                {"id": 9, "type": "integer", "name": "temp_set_f", "range": {"min": 32, "max": 212}},\n                {"id": 12, "type": "string", "name": "temperature_unit"},\n            ],\n        }\n        with self.assertRaisesRegex(base.ConversionError, "advanced_mapping_condition_semantics"):\n            base._CONVERTERS["water_heater"](entity)\n\n    def test_mismatched_temperature_scales_fail_closed(self):\n        entity = {\n            "entity": "water_heater",\n            "dps": [\n                {"id": 1, "type": "boolean", "name": "operation_mode", "mapping": [\n                    {"dps_val": False, "value": "off"}, {"dps_val": True, "value": "electric"}\n                ]},\n                {"id": 2, "type": "integer", "name": "temperature", "range": {"min": 10, "max": 60}, "mapping": [{"scale": 10}]},\n                {"id": 3, "type": "integer", "name": "current_temperature"},\n            ],\n        }\n        with self.assertRaisesRegex(base.ConversionError, "water_heater_temperature_scale_mismatch"):\n            productless._convert_water_heater_productless(entity)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''', encoding='utf-8')
