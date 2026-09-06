from pathlib import Path

path = Path('tools/import_tuya_local_productless.py')
text = path.read_text(encoding='utf-8')

start = text.index('def _project_mapping_for_base(')
end = text.index('\n\ndef _validate_consumed_dependency', start)
new = '''def _project_mapping_for_base(
    dp: dict[str, Any], platform: str, name: str
) -> dict[str, Any]:
    """Project mappings only when a base converter needs a finite HA enum domain."""
    enum_names = {
        "climate": {
            "hvac_mode", "preset_mode", "fan_mode", "swing_mode",
            "swing_horizontal_mode", "hvac_action", "temperature_unit",
        },
    }
    if name not in enum_names.get(platform, set()):
        projected = copy.deepcopy(dp)
        rules = _raw_mapping(dp)
        output: list[dict[str, Any]] = []
        for source in rules:
            rule = {
                key: copy.deepcopy(value)
                for key, value in source.items()
                if key not in _BASE_PROJECTION_DROP
                and key not in _UNSUPPORTED_ADVANCED_KEYS
            }
            if rule:
                output.append(rule)
        if output:
            projected["mapping"] = output
        else:
            projected.pop("mapping", None)
        return projected

    projected = copy.deepcopy(dp)
    rules = _raw_mapping(dp)
    outputs: list[Any] = []
    missing = object()

    def add_output(value: Any) -> None:
        if value is missing:
            raise ConversionError("advanced_mapping_unbounded_output")
        value = _runtime_scalar(value, "advanced_mapping_projection_scalar")
        if value is None:
            raise ConversionError("advanced_mapping_projection_none")
        if not any(value == seen and type(value) is type(seen) for seen in outputs):
            outputs.append(value)

    for source in rules:
        if source.get("invalid") is True or source.get("hidden") is True:
            continue
        conditions = source.get("conditions")
        if isinstance(conditions, list) and conditions:
            for condition in conditions:
                if not isinstance(condition, dict):
                    raise ConversionError("advanced_mapping_condition")
                if condition.get("invalid") is True or condition.get("hidden") is True:
                    continue
                add_output(condition.get(
                    "value", source.get("value", source.get("dps_val", missing))
                ))
        else:
            add_output(source.get("value", source.get("dps_val", missing)))

    if not outputs:
        raise ConversionError("advanced_mapping_empty_projection")
    kinds = {bool if isinstance(v, bool) else type(v) for v in outputs}
    if len(kinds) != 1:
        raise ConversionError("advanced_mapping_mixed_output_types")
    kind = next(iter(kinds))
    if kind is str:
        projected["type"] = "string"
    elif kind is bool:
        projected["type"] = "boolean"
    elif kind is int:
        projected["type"] = "integer"
    else:
        raise ConversionError("advanced_mapping_projection_type")
    projected["mapping"] = [
        {"dps_val": value, "value": value} for value in outputs
    ]
    return projected
'''
text = text[:start] + new + text[end:]
old = 'transformed_by_name[name].update(_project_mapping_for_base(original_dp))'
new_call = 'transformed_by_name[name].update(_project_mapping_for_base(original_dp, platform, name))'
if old not in text:
    raise SystemExit('projection call not found')
text = text.replace(old, new_call, 1)
path.write_text(text, encoding='utf-8')
