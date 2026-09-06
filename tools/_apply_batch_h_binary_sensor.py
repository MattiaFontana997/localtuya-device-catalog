from pathlib import Path

path = Path('tools/import_tuya_local_productless.py')
text = path.read_text(encoding='utf-8')

marker = '\n\n# Extend only the productless conversion surface.'
insert = r'''

_BINARY_SENSOR_EXTENDED_REASONS = {
    "binary_sensor_dp_type",
    "binary_sensor_complex_mapping",
    "binary_sensor_ambiguous_on",
    "binary_sensor_ambiguous_off",
    "binary_sensor_incomplete_mapping",
}


def _binary_sensor_raw_value(value: Any, dp_type: str) -> str | int | bool | None:
    if value is None:
        return None
    if dp_type in {"integer", "bitfield"}:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConversionError("binary_sensor_mapping_raw_type")
        return value
    if dp_type == "string":
        if not isinstance(value, str):
            raise ConversionError("binary_sensor_mapping_raw_type")
        return value
    if dp_type == "boolean":
        if not isinstance(value, bool):
            raise ConversionError("binary_sensor_mapping_raw_type")
        return value
    raise ConversionError("binary_sensor_dp_type")


def _convert_binary_sensor_productless(entity: dict[str, Any]) -> base.Converted:
    """Extend binary sensors with ordered exact/bitfield/catch-all mappings.

    Preserve the mature converter output whenever it is already lossless. The
    extended catalog-only grammar is used only for source mappings that the
    legacy state_on/state_off pair cannot represent.
    """
    try:
        return base._convert_binary_sensor(entity)
    except ConversionError as err:
        if str(err) not in _BINARY_SENSOR_EXTENDED_REASONS:
            raise

    dp = base._single_named_dp(entity, "sensor")
    base._check_common_dp_semantics(dp, writable=False)
    dp_type = base._dp_type(dp)
    if dp_type not in {"boolean", "integer", "string", "bitfield"}:
        raise ConversionError("binary_sensor_dp_type")

    rules = base._mapping_rules(dp)
    if not rules:
        raise ConversionError("binary_sensor_requires_mapping")
    if len(rules) > 32:
        raise ConversionError("binary_sensor_too_many_mapping_rules")

    normalized: list[dict[str, Any]] = []
    default_count = 0
    for rule in rules:
        if set(rule) - {"dps_val", "value"} or "value" not in rule:
            raise ConversionError("binary_sensor_complex_mapping")
        if not isinstance(rule["value"], bool):
            raise ConversionError("binary_sensor_non_boolean_mapping")
        item: dict[str, Any] = {"value": rule["value"]}
        if "dps_val" in rule:
            item["dps_val"] = _binary_sensor_raw_value(rule["dps_val"], dp_type)
        else:
            default_count += 1
            if default_count > 1:
                raise ConversionError("binary_sensor_multiple_defaults")
        normalized.append(item)

    config: dict[str, Any] = {
        "id": base._dp_id(dp),
        "platform": "binary_sensor",
        "binary_sensor_mapping": normalized,
    }
    if dp_type == "bitfield":
        config["binary_sensor_bitfield"] = True
    base._entity_metadata(entity, config)
    return base._finish_single_entity("binary_sensor", config, dp)
'''

if '_convert_binary_sensor_productless' not in text:
    if marker not in text:
        raise SystemExit('extension marker not found')
    text = text.replace(marker, insert + marker, 1)

old = '_original_converters = dict(base._CONVERTERS)\nfor _platform, _converter in _original_converters.items():'
new = '_original_converters = dict(base._CONVERTERS)\n_original_converters["binary_sensor"] = _convert_binary_sensor_productless\nfor _platform, _converter in _original_converters.items():'
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit('converter installation marker not found')

path.write_text(text, encoding='utf-8')
