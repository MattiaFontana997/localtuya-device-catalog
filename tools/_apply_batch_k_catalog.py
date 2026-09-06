from pathlib import Path
import json

path = Path('tools/import_tuya_local_productless.py')
text = path.read_text(encoding='utf-8')
old = 'from sensor_mapping import validate_sensor_value_mapping\n'
new = '''from sensor_mapping import validate_sensor_value_mapping
from fan_mapping import (
    coerce_fan_raw,
    validate_fan_oscillation_mapping,
    validate_fan_speed_mapping,
)
'''
if old not in text:
    raise SystemExit('productless import marker missing')
text = text.replace(old, new, 1)

marker = '\n\ndef _convert_binary_sensor_productless('
insert = r'''

_FAN_EXTENDED_REASONS = {
    "fan_speed_percentages",
    "fan_speed_mapping",
    "fan_oscillate_mapping",
    "fan_preset_type",
    "fan_preset_optional",
}


def _fan_productless_dps(entity: dict[str, Any]) -> dict[str, dict[str, Any]]:
    dps = entity.get("dps")
    if not isinstance(dps, list) or not dps:
        raise ConversionError("fan_missing_dps")
    result: dict[str, dict[str, Any]] = {}
    for dp in dps:
        if not isinstance(dp, dict):
            raise ConversionError("invalid_dp")
        name = dp.get("name")
        if not isinstance(name, str) or not name:
            raise ConversionError("fan_missing_dp_name")
        if name in result:
            raise ConversionError(f"fan_duplicate_dp:{name}")
        result[name] = dp
    return result


def _fan_productless_speed(dp: dict[str, Any], config: dict[str, Any]) -> None:
    try:
        base._fan_speed_config(dp, config)
        return
    except ConversionError as err:
        if str(err) not in {"fan_speed_percentages", "fan_speed_mapping"}:
            raise

    base._check_common_dp_semantics(dp, writable=True)
    raw_type = base._dp_type(dp)
    if raw_type not in {"string", "integer"}:
        raise ConversionError("fan_speed_type")
    normalized_rules = []
    for rule in _raw_mapping(dp):
        if set(rule) - {"dps_val", "value", "hidden"}:
            raise ConversionError("fan_speed_mapping")
        if rule.get("hidden") is True:
            # A hidden exact -> null rule is read-only in Tuya Local. Omitting
            # it leaves the HA speed unavailable for that raw state and cannot
            # make it writable, which is the same observable fan behaviour.
            if "dps_val" in rule and rule.get("value") is None:
                continue
            raise ConversionError("fan_speed_mapping")
        if "dps_val" not in rule or "value" not in rule:
            raise ConversionError("fan_speed_mapping")
        normalized_rules.append({"dps_val": rule["dps_val"], "value": rule["value"]})
    spec = validate_fan_speed_mapping({"raw_type": raw_type, "rules": normalized_rules})
    if spec is None:
        raise ConversionError("fan_speed_mapping")
    config["fan_speed_control"] = base._dp_id(dp)
    config["fan_speed_mapping"] = spec


def _fan_productless_oscillation(dp: dict[str, Any], config: dict[str, Any]) -> None:
    try:
        raw_on, raw_off = base._fan_boolean_values(dp, "fan_oscillate_mapping")
    except ConversionError as err:
        if str(err) != "fan_oscillate_mapping":
            raise
    else:
        config["fan_oscillating_control"] = base._dp_id(dp)
        if base._dp_type(dp) != "boolean" or raw_on is not True or raw_off is not False:
            config["fan_oscillating_on"] = raw_on
            config["fan_oscillating_off"] = raw_off
        return

    base._check_common_dp_semantics(dp, writable=True)
    raw_type = base._dp_type(dp)
    if raw_type not in {"string", "integer", "boolean"}:
        raise ConversionError("fan_oscillate_mapping")
    rules = []
    for rule in _raw_mapping(dp):
        if set(rule) - {"dps_val", "value", "hidden"} or "value" not in rule:
            raise ConversionError("fan_oscillate_mapping")
        if rule.get("hidden") is True:
            raise ConversionError("fan_oscillate_mapping")
        item = {"value": rule["value"]}
        if "dps_val" in rule:
            item["dps_val"] = rule["dps_val"]
        rules.append(item)
    spec = validate_fan_oscillation_mapping({"raw_type": raw_type, "rules": rules})
    if spec is None:
        raise ConversionError("fan_oscillate_mapping")
    config["fan_oscillating_control"] = base._dp_id(dp)
    config["fan_oscillating_mapping"] = spec


def _fan_productless_presets(dp: dict[str, Any], config: dict[str, Any]) -> None:
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


def _convert_fan_productless(entity: dict[str, Any]) -> base.Converted:
    """Extend productless fans with exact enumerated mapping semantics."""
    try:
        return base._convert_fan(entity)
    except ConversionError as err:
        reason = str(err)
        if reason not in _FAN_EXTENDED_REASONS and not reason.startswith("fan_unsupported_dp:"):
            raise

    if entity.get("class") is not None:
        raise ConversionError("fan_device_class")
    base._entity_metadata(entity, {})
    dps = _fan_productless_dps(entity)
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
    if speed is not None:
        _fan_productless_speed(speed, config)
        base._merge_membership(required, optional, speed)

    preset = dps.get("preset_mode")
    if preset is not None:
        _fan_productless_presets(preset, config)
        base._merge_membership(required, optional, preset)

    oscillate = dps.get("oscillate")
    if oscillate is not None:
        _fan_productless_oscillation(oscillate, config)
        base._merge_membership(required, optional, oscillate)

    direction = dps.get("direction")
    if direction is not None:
        base._fan_direction_config(direction, config)
        base._merge_membership(required, optional, direction)

    functional = {"switch", "speed", "preset_mode", "oscillate", "direction"}
    for name, dp in dps.items():
        if name in functional:
            continue
        base._preserve_core_extra("fan", name, dp, config, required, optional)

    return {"platform": "fan", "config": config}, required, optional
'''
if marker not in text:
    raise SystemExit('fan insertion marker missing')
text = text.replace(marker, insert + marker, 1)

old = '''_original_converters["binary_sensor"] = _convert_binary_sensor_productless\n_original_converters["sensor"] = _convert_sensor_productless'''
new = '''_original_converters["binary_sensor"] = _convert_binary_sensor_productless
_original_converters["sensor"] = _convert_sensor_productless
_original_converters["fan"] = _convert_fan_productless'''
if old not in text:
    raise SystemExit('fan converter registration marker missing')
text = text.replace(old, new, 1)
path.write_text(text, encoding='utf-8')

validator = Path('tools/validate_catalog.py')
text = validator.read_text(encoding='utf-8')
old = '''try:\n    from .sensor_mapping import validate_sensor_value_mapping\nexcept ImportError:  # Direct script execution.\n    from sensor_mapping import validate_sensor_value_mapping'''
new = '''try:
    from .sensor_mapping import validate_sensor_value_mapping
    from .fan_mapping import (
        RAW_TYPES as FAN_RAW_TYPES,
        coerce_fan_raw,
        validate_fan_oscillation_mapping,
        validate_fan_speed_mapping,
    )
except ImportError:  # Direct script execution.
    from sensor_mapping import validate_sensor_value_mapping
    from fan_mapping import (
        RAW_TYPES as FAN_RAW_TYPES,
        coerce_fan_raw,
        validate_fan_oscillation_mapping,
        validate_fan_speed_mapping,
    )'''
if old not in text:
    raise SystemExit('validator import marker missing')
text = text.replace(old, new, 1)

old = '''            if "sensor_value_mapping" in config:\n                if (platform != "sensor" or validate_sensor_value_mapping(config["sensor_value_mapping"]) is None\n                        or any(key in config for key in ("scaling", "advanced_mapping", "advanced_mapping_by_dp"))):\n                    errors.append(f"{source}: mapping {mapping_id!r} invalid sensor value mapping")\n            override_keys = entity.get("override_keys", [])'''
new = '''            if "sensor_value_mapping" in config:
                if (platform != "sensor" or validate_sensor_value_mapping(config["sensor_value_mapping"]) is None
                        or any(key in config for key in ("scaling", "advanced_mapping", "advanced_mapping_by_dp"))):
                    errors.append(f"{source}: mapping {mapping_id!r} invalid sensor value mapping")
            if "fan_speed_mapping" in config:
                if platform != "fan" or "fan_speed_control" not in config or validate_fan_speed_mapping(config["fan_speed_mapping"]) is None:
                    errors.append(f"{source}: mapping {mapping_id!r} invalid fan speed mapping")
            if "fan_oscillating_mapping" in config:
                if platform != "fan" or "fan_oscillating_control" not in config or validate_fan_oscillation_mapping(config["fan_oscillating_mapping"]) is None:
                    errors.append(f"{source}: mapping {mapping_id!r} invalid fan oscillation mapping")
            if "fan_preset_raw_type" in config:
                raw_type = config["fan_preset_raw_type"]
                values = config.get("fan_preset_values")
                if platform != "fan" or raw_type not in FAN_RAW_TYPES or "fan_preset_dp" not in config or not isinstance(values, dict) or not values:
                    errors.append(f"{source}: mapping {mapping_id!r} invalid fan preset raw type")
                else:
                    seen_raw = []
                    for raw in values.values():
                        try:
                            normalized = coerce_fan_raw(raw, raw_type)
                        except ValueError:
                            errors.append(f"{source}: mapping {mapping_id!r} invalid fan preset raw value")
                            break
                        if any(normalized == previous for previous in seen_raw):
                            errors.append(f"{source}: mapping {mapping_id!r} duplicate fan preset raw value")
                            break
                        seen_raw.append(normalized)
            override_keys = entity.get("override_keys", [])'''
if old not in text:
    raise SystemExit('validator semantic marker missing')
text = text.replace(old, new, 1)
validator.write_text(text, encoding='utf-8')

schema_path = Path('schema/catalog.schema.json')
schema = json.loads(schema_path.read_text(encoding='utf-8'))
defs = schema['$defs']
config_props = defs['entity']['properties']['config']['properties']
config_props['fan_speed_mapping'] = {'$ref': '#/$defs/fan_speed_mapping'}
config_props['fan_oscillating_mapping'] = {'$ref': '#/$defs/fan_oscillating_mapping'}
config_props['fan_preset_raw_type'] = {'enum': ['string', 'integer', 'boolean']}
defs['fan_speed_mapping'] = {
    'type': 'object', 'required': ['raw_type', 'rules'], 'additionalProperties': False,
    'properties': {
        'raw_type': {'enum': ['string', 'integer']},
        'rules': {'type': 'array', 'minItems': 2, 'maxItems': 64, 'items': {
            'type': 'object', 'required': ['dps_val', 'value'], 'additionalProperties': False,
            'properties': {
                'dps_val': {'type': ['string', 'integer']},
                'value': {'type': 'number', 'exclusiveMinimum': 0, 'maximum': 100},
            },
        }},
    },
}
defs['fan_oscillating_mapping'] = {
    'type': 'object', 'required': ['raw_type', 'rules'], 'additionalProperties': False,
    'properties': {
        'raw_type': {'enum': ['string', 'integer', 'boolean']},
        'rules': {'type': 'array', 'minItems': 2, 'maxItems': 32, 'items': {
            'type': 'object', 'required': ['value'], 'additionalProperties': False,
            'properties': {
                'dps_val': {'type': ['string', 'integer', 'boolean']},
                'value': {'type': 'boolean'},
            },
        }},
    },
}
schema_path.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
