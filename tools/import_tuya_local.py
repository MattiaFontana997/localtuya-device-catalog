"""Convert a conservative subset of Tuya Local profiles to Catalog V2.

The importer intentionally fails closed. A profile is emitted only when every
entity and datapoint semantic used by that profile can be represented by the
current LocalTuya entity configuration without silently dropping behaviour.

Imported mappings are always ``experimental`` and retain MIT provenance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

try:
    import yaml
except ImportError as err:  # pragma: no cover
    raise SystemExit(
        "PyYAML is required for this tool. Install it with: "
        "python -m pip install 'PyYAML>=6,<7'"
    ) from err


SOURCE_REPOSITORY = "make-all/tuya-local"
SOURCE_LICENSE = "MIT"
SUPPORTED_PLATFORMS = {
    "binary_sensor",
    "light",
    "number",
    "select",
    "sensor",
    "switch",
}
ADVANCED_MAPPING_KEYS = {
    "available",
    "conditions",
    "constraint",
    "invalid",
    "mapping",
    "value_mirror",
    "value_redirect",
}
UNSUPPORTED_DP_FLAGS = {
    "force",
    "persist",
    "sensitive",
}


class ConversionError(ValueError):
    """Raised when conversion would lose source semantics."""


@dataclass(frozen=True, slots=True)
class ImportResult:
    """One source profile conversion result."""

    file: str
    name: str
    status: str
    mapping_id: str | None
    product_ids: tuple[str, ...]
    platforms: tuple[str, ...]
    reasons: tuple[str, ...]


Converted = tuple[dict[str, Any], set[int], set[int]]
Converter = Callable[[dict[str, Any]], Converted]


def _devices_dir(source: Path) -> Path:
    source = source.expanduser().resolve()
    candidate = source / "custom_components" / "tuya_local" / "devices"
    if candidate.is_dir():
        return candidate
    if source.is_dir() and source.name == "devices":
        return source
    raise FileNotFoundError(
        "Could not find custom_components/tuya_local/devices under "
        f"{source}"
    )


def _product_ids(profile: dict[str, Any]) -> list[str]:
    result: list[str] = []
    products = profile.get("products")
    if not isinstance(products, list):
        return result

    for product in products:
        if not isinstance(product, dict):
            continue
        value = product.get("id")
        if value is None:
            continue
        product_id = str(value).strip()
        if product_id and product_id not in result:
            result.append(product_id)
    return sorted(result)


def _platforms(profile: dict[str, Any]) -> list[str]:
    result: list[str] = []
    entities = profile.get("entities")
    if not isinstance(entities, list):
        return result
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        platform = entity.get("entity")
        if isinstance(platform, str):
            platform = platform.strip()
            if platform and platform not in result:
                result.append(platform)
    return result


def _dp_id(dp: dict[str, Any]) -> int:
    value = dp.get("id")
    if isinstance(value, bool):
        raise ConversionError("invalid_dp_id")
    try:
        dp_id = int(value)
    except (TypeError, ValueError) as err:
        raise ConversionError("invalid_dp_id") from err
    if dp_id <= 0 or dp_id > 65535:
        raise ConversionError("invalid_dp_id")
    return dp_id


def _dp_type(dp: dict[str, Any]) -> str:
    value = dp.get("type")
    if not isinstance(value, str) or not value.strip():
        raise ConversionError("missing_dp_type")
    return value.strip().lower()


def _check_common_dp_semantics(dp: dict[str, Any], *, writable: bool) -> None:
    """Reject DP features whose runtime behaviour is not represented yet."""
    if dp.get("hidden") is True:
        raise ConversionError("dp_hidden")

    if dp.get("force") is True:
        raise ConversionError("dp_force")

    if dp.get("persist") is False:
        raise ConversionError("dp_persist_false")

    if dp.get("sensitive") is True:
        raise ConversionError("dp_sensitive")

    if writable and dp.get("readonly") is True:
        raise ConversionError("dp_readonly")

    for flag in UNSUPPORTED_DP_FLAGS:
        value = dp.get(flag)
        if flag == "persist":
            continue
        if value not in (None, False):
            raise ConversionError(f"dp_{flag}")


def _mapping_rules(dp: dict[str, Any]) -> list[dict[str, Any]]:
    mapping = dp.get("mapping")
    if mapping is None:
        return []
    if not isinstance(mapping, list):
        raise ConversionError("invalid_mapping")

    result: list[dict[str, Any]] = []
    for rule in mapping:
        if not isinstance(rule, dict):
            raise ConversionError("invalid_mapping_rule")
        if set(rule) & ADVANCED_MAPPING_KEYS:
            raise ConversionError("advanced_mapping")
        result.append(rule)
    return result


def _single_named_dp(entity: dict[str, Any], name: str) -> dict[str, Any]:
    dps = entity.get("dps")
    if not isinstance(dps, list) or not dps:
        raise ConversionError("missing_dps")

    if len(dps) != 1:
        # Extra Tuya Local attributes would otherwise disappear silently.
        raise ConversionError("multi_dp_entity")

    dp = dps[0]
    if not isinstance(dp, dict):
        raise ConversionError("invalid_dp")
    if dp.get("name") != name:
        raise ConversionError(f"expected_dp_name:{name}")
    return dp


def _entity_metadata(entity: dict[str, Any], config: dict[str, Any]) -> None:
    """Transfer compatible HA metadata from the Tuya Local entity."""
    device_class = entity.get("class")
    if device_class is not None:
        if not isinstance(device_class, str) or not device_class.strip():
            raise ConversionError("invalid_device_class")
        config["device_class"] = device_class.strip()

    # LocalTuya currently cannot reproduce disabled-by-default semantics from
    # Tuya Local profile-level hidden flags.
    if entity.get("hidden") not in (None, False):
        raise ConversionError("entity_hidden")

    mode = entity.get("mode")
    if mode not in (None, "auto"):
        raise ConversionError("entity_mode")


def _dp_membership(dp: dict[str, Any]) -> tuple[set[int], set[int]]:
    dp_id = _dp_id(dp)
    if bool(dp.get("optional")):
        return set(), {dp_id}
    return {dp_id}, set()


def _finish_single_entity(
    platform: str,
    config: dict[str, Any],
    dp: dict[str, Any],
) -> Converted:
    required, optional = _dp_membership(dp)
    return {"platform": platform, "config": config}, required, optional


def _identity_boolean_mapping(dp: dict[str, Any], reason: str) -> None:
    rules = _mapping_rules(dp)
    if not rules:
        return

    expected = {False: False, True: True}
    observed: dict[bool, bool] = {}
    for rule in rules:
        if set(rule) != {"dps_val", "value"}:
            raise ConversionError(reason)
        raw = rule["dps_val"]
        value = rule["value"]
        if not isinstance(raw, bool) or not isinstance(value, bool):
            raise ConversionError(reason)
        observed[raw] = value
    if observed != expected:
        raise ConversionError(reason)


def _convert_switch(entity: dict[str, Any]) -> Converted:
    dp = _single_named_dp(entity, "switch")
    _check_common_dp_semantics(dp, writable=True)
    if _dp_type(dp) != "boolean":
        raise ConversionError("switch_non_boolean")
    _identity_boolean_mapping(dp, "switch_non_identity_mapping")

    dp_id = _dp_id(dp)
    config: dict[str, Any] = {
        "id": dp_id,
        "platform": "switch",
        "restore_on_reconnect": False,
        "is_passive_entity": False,
    }
    _entity_metadata(entity, config)
    return _finish_single_entity("switch", config, dp)


def _binary_mapping(dp: dict[str, Any]) -> tuple[str, str]:
    rules = _mapping_rules(dp)
    if not rules:
        if _dp_type(dp) != "boolean":
            raise ConversionError("binary_sensor_requires_mapping")
        return "True", "False"

    raw_on = None
    raw_off = None
    for rule in rules:
        if set(rule) != {"dps_val", "value"}:
            raise ConversionError("binary_sensor_complex_mapping")
        value = rule["value"]
        if not isinstance(value, bool):
            raise ConversionError("binary_sensor_non_boolean_mapping")
        if value:
            if raw_on is not None:
                raise ConversionError("binary_sensor_ambiguous_on")
            raw_on = rule["dps_val"]
        else:
            if raw_off is not None:
                raise ConversionError("binary_sensor_ambiguous_off")
            raw_off = rule["dps_val"]

    if raw_on is None or raw_off is None:
        raise ConversionError("binary_sensor_incomplete_mapping")
    return str(raw_on), str(raw_off)


def _convert_binary_sensor(entity: dict[str, Any]) -> Converted:
    dp = _single_named_dp(entity, "sensor")
    _check_common_dp_semantics(dp, writable=False)
    if _dp_type(dp) not in {"boolean", "integer", "string"}:
        raise ConversionError("binary_sensor_dp_type")

    state_on, state_off = _binary_mapping(dp)
    dp_id = _dp_id(dp)
    config: dict[str, Any] = {
        "id": dp_id,
        "platform": "binary_sensor",
        "state_on": state_on,
        "state_off": state_off,
    }
    _entity_metadata(entity, config)
    return _finish_single_entity("binary_sensor", config, dp)


def _default_scale_rule(dp: dict[str, Any]) -> float:
    """Return LocalTuya multiplier for a lossless Tuya Local scale rule."""
    rules = _mapping_rules(dp)
    if not rules:
        return 1.0
    if len(rules) != 1:
        raise ConversionError("non_uniform_numeric_mapping")

    rule = rules[0]
    if "dps_val" in rule:
        raise ConversionError("value_specific_numeric_mapping")
    if set(rule) - {"scale"}:
        raise ConversionError("unsupported_numeric_mapping")

    scale = rule.get("scale", 1)
    if isinstance(scale, bool):
        raise ConversionError("invalid_scale")
    try:
        divisor = float(scale)
    except (TypeError, ValueError) as err:
        raise ConversionError("invalid_scale") from err
    if not math.isfinite(divisor) or divisor == 0:
        raise ConversionError("invalid_scale")
    return 1.0 / divisor


def _convert_sensor(entity: dict[str, Any]) -> Converted:
    dp = _single_named_dp(entity, "sensor")
    _check_common_dp_semantics(dp, writable=False)
    if _dp_type(dp) not in {"boolean", "integer", "string"}:
        raise ConversionError("sensor_dp_type")
    if dp.get("precision") is not None:
        raise ConversionError("sensor_precision")

    scaling = _default_scale_rule(dp)
    dp_id = _dp_id(dp)
    config: dict[str, Any] = {
        "id": dp_id,
        "platform": "sensor",
    }
    if scaling != 1.0:
        config["scaling"] = scaling

    unit = dp.get("unit")
    if unit is not None:
        if not isinstance(unit, str):
            raise ConversionError("invalid_unit")
        config["unit_of_measurement"] = unit

    state_class = dp.get("class")
    if state_class is not None:
        if not isinstance(state_class, str):
            raise ConversionError("invalid_state_class")
        config["state_class"] = state_class

    _entity_metadata(entity, config)
    return _finish_single_entity("sensor", config, dp)


def _numeric_rule(dp: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    rules = _mapping_rules(dp)
    rule: dict[str, Any] = {}
    if rules:
        if len(rules) != 1 or "dps_val" in rules[0]:
            raise ConversionError("non_uniform_number_mapping")
        rule = rules[0]
        if set(rule) - {"scale", "step", "range"}:
            raise ConversionError("unsupported_number_mapping")

    scale = rule.get("scale", 1)
    if isinstance(scale, bool):
        raise ConversionError("invalid_scale")
    try:
        divisor = float(scale)
    except (TypeError, ValueError) as err:
        raise ConversionError("invalid_scale") from err
    if not math.isfinite(divisor) or divisor <= 0:
        raise ConversionError("invalid_scale")
    return 1.0 / divisor, rule


def _range_value(value: Any, scaling: float, reason: str) -> float:
    if isinstance(value, bool):
        raise ConversionError(reason)
    try:
        result = float(value) * scaling
    except (TypeError, ValueError) as err:
        raise ConversionError(reason) from err
    if not math.isfinite(result):
        raise ConversionError(reason)
    return result


def _convert_number(entity: dict[str, Any]) -> Converted:
    dp = _single_named_dp(entity, "value")
    _check_common_dp_semantics(dp, writable=True)
    if _dp_type(dp) != "integer":
        raise ConversionError("number_non_integer")

    scaling, rule = _numeric_rule(dp)
    range_config = rule.get("range", dp.get("range"))
    if not isinstance(range_config, dict):
        raise ConversionError("number_missing_range")
    if "min" not in range_config or "max" not in range_config:
        raise ConversionError("number_invalid_range")

    minimum = _range_value(range_config["min"], scaling, "number_invalid_min")
    maximum = _range_value(range_config["max"], scaling, "number_invalid_max")
    if maximum < minimum:
        raise ConversionError("number_invalid_range")

    raw_step = rule.get("step", dp.get("step", 1))
    step = _range_value(raw_step, scaling, "number_invalid_step")
    if step <= 0:
        raise ConversionError("number_invalid_step")

    dp_id = _dp_id(dp)
    config: dict[str, Any] = {
        "id": dp_id,
        "platform": "number",
        "min_value": minimum,
        "max_value": maximum,
        "step_size": step,
        "scaling": scaling,
        "restore_on_reconnect": False,
        "is_passive_entity": False,
    }

    unit = dp.get("unit")
    if unit is not None:
        if not isinstance(unit, str):
            raise ConversionError("invalid_unit")
        config["unit_of_measurement"] = unit

    _entity_metadata(entity, config)
    return _finish_single_entity("number", config, dp)


def _convert_select(entity: dict[str, Any]) -> Converted:
    dp = _single_named_dp(entity, "option")
    _check_common_dp_semantics(dp, writable=True)
    if _dp_type(dp) != "string":
        raise ConversionError("select_non_string")

    rules = _mapping_rules(dp)
    if not rules:
        raise ConversionError("select_missing_mapping")

    raw_options: list[str] = []
    display_options: list[str] = []
    for rule in rules:
        if set(rule) - {"dps_val", "value", "hidden"}:
            raise ConversionError("select_complex_mapping")
        if rule.get("hidden") is True:
            raise ConversionError("select_hidden_option")
        if "dps_val" not in rule or "value" not in rule:
            raise ConversionError("select_incomplete_mapping")
        raw = rule["dps_val"]
        display = rule["value"]
        if not isinstance(raw, str) or not isinstance(display, str):
            raise ConversionError("select_non_string_mapping")
        if ";" in raw or ";" in display:
            raise ConversionError("select_semicolon_value")
        if raw in raw_options or display in display_options:
            raise ConversionError("select_duplicate_option")
        raw_options.append(raw)
        display_options.append(display)

    dp_id = _dp_id(dp)
    config: dict[str, Any] = {
        "id": dp_id,
        "platform": "select",
        "options": ";".join(raw_options),
        "restore_on_reconnect": False,
        "is_passive_entity": False,
    }
    if display_options != raw_options:
        config["options_friendly"] = ";".join(display_options)

    if entity.get("class") is not None:
        raise ConversionError("select_device_class")
    _entity_metadata(entity, config)
    return _finish_single_entity("select", config, dp)


def _raw_integer_range(dp: dict[str, Any], reason: str) -> tuple[int, int]:
    raw_range = dp.get("range")
    if not isinstance(raw_range, dict):
        raise ConversionError(f"{reason}_missing_range")
    if set(raw_range) != {"min", "max"}:
        raise ConversionError(f"{reason}_invalid_range")

    values: list[int] = []
    for key in ("min", "max"):
        value = raw_range[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConversionError(f"{reason}_invalid_range")
        if not math.isfinite(float(value)) or int(value) != value:
            raise ConversionError(f"{reason}_invalid_range")
        values.append(int(value))

    minimum, maximum = values
    if minimum < 0 or maximum <= minimum or maximum > 10000:
        raise ConversionError(f"{reason}_invalid_range")
    return minimum, maximum


def _light_dps(entity: dict[str, Any]) -> dict[str, dict[str, Any]]:
    dps = entity.get("dps")
    if not isinstance(dps, list) or not dps:
        raise ConversionError("light_missing_dps")

    supported = {"switch", "brightness", "color_mode", "color_temp", "rgbhsv", "effect"}
    result: dict[str, dict[str, Any]] = {}
    for dp in dps:
        if not isinstance(dp, dict):
            raise ConversionError("invalid_dp")
        name = dp.get("name")
        if not isinstance(name, str) or not name:
            raise ConversionError("light_missing_dp_name")
        if name not in supported:
            raise ConversionError(f"light_unsupported_dp:{name}")
        if name in result:
            raise ConversionError(f"light_duplicate_dp:{name}")
        result[name] = dp
    return result


def _merge_membership(
    required: set[int], optional: set[int], dp: dict[str, Any]
) -> None:
    dp_required, dp_optional = _dp_membership(dp)
    required.update(dp_required)
    optional.update(dp_optional)


def _light_has_bare_scene(entity: dict[str, Any]) -> bool:
    dps = entity.get("dps")
    if not isinstance(dps, list):
        return False

    for dp in dps:
        if not isinstance(dp, dict) or dp.get("name") != "color_mode":
            continue
        mapping = dp.get("mapping")
        if not isinstance(mapping, list):
            return False
        return any(
            isinstance(rule, dict) and rule.get("dps_val") == "scene"
            for rule in mapping
        )

    return False


def _scene_select_values(
    entity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]] | None:
    if (
        entity.get("entity") != "select"
        or entity.get("translation_key") != "scene"
    ):
        return None

    try:
        dp = _single_named_dp(entity, "option")
        _check_common_dp_semantics(dp, writable=True)
        if _dp_type(dp) != "string":
            return None
        rules = _mapping_rules(dp)
    except ConversionError:
        return None

    if not rules:
        return None

    values: dict[str, str] = {}
    raw_values: set[str] = set()
    for rule in rules:
        if set(rule) - {"dps_val", "value", "hidden"}:
            return None
        if rule.get("hidden") is True:
            return None
        raw = rule.get("dps_val")
        friendly = rule.get("value")
        if (
            not isinstance(raw, str)
            or not raw
            or not isinstance(friendly, str)
            or not friendly.strip()
        ):
            return None
        friendly = friendly.strip()
        if raw in raw_values or friendly in values:
            return None
        raw_values.add(raw)
        values[friendly] = raw

    return dp, values


def _hidden_scene_text_dp(
    entity: dict[str, Any], scene_dp: dict[str, Any]
) -> dict[str, Any] | None:
    if (
        entity.get("entity") != "text"
        or entity.get("translation_key") != "scene"
        or entity.get("hidden") is not True
    ):
        return None

    try:
        dp = _single_named_dp(entity, "value")
        if _dp_id(dp) != _dp_id(scene_dp):
            return None
        if _dp_membership(dp) != _dp_membership(scene_dp):
            return None
    except ConversionError:
        return None

    return dp


def _find_light_scene_context(
    entities: list[Any],
) -> tuple[int, dict[str, Any], dict[str, str], int] | None:
    light_indexes = [
        index
        for index, entity in enumerate(entities)
        if isinstance(entity, dict)
        and entity.get("entity") == "light"
        and _light_has_bare_scene(entity)
    ]
    if len(light_indexes) != 1:
        return None

    candidates: list[tuple[int, dict[str, Any], dict[str, str], int]] = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        parsed = _scene_select_values(entity)
        if parsed is None:
            continue
        scene_dp, scene_values = parsed

        hidden_indexes = [
            index
            for index, hidden in enumerate(entities)
            if isinstance(hidden, dict)
            and _hidden_scene_text_dp(hidden, scene_dp) is not None
        ]
        if len(hidden_indexes) != 1:
            continue

        candidates.append(
            (light_indexes[0], scene_dp, scene_values, hidden_indexes[0])
        )

    if len(candidates) != 1:
        return None
    return candidates[0]


def _configure_light_scale(
    config: dict[str, Any],
    *,
    minimum: int,
    maximum: int,
    reason: str,
    require_lower: bool,
) -> None:
    existing_upper = config.get("brightness_upper")
    existing_lower = config.get("brightness_lower")

    if reason == "light_rgbhsv":
        if existing_upper is None and existing_lower is None:
            config["brightness_lower"] = minimum
            config["brightness_upper"] = maximum
            return

        if existing_lower == minimum and existing_upper == maximum:
            return

        config["color_brightness_lower"] = minimum
        config["color_brightness_upper"] = maximum
        return

    if existing_upper is not None and existing_upper != maximum:
        raise ConversionError(f"{reason}_range_mismatch")

    if require_lower and existing_lower is not None and existing_lower != minimum:
        raise ConversionError(f"{reason}_range_mismatch")

    if existing_upper is None:
        config["brightness_upper"] = maximum
    if existing_lower is None:
        config["brightness_lower"] = minimum if require_lower else 0


def _convert_light(
    entity: dict[str, Any],
    *,
    scene_dp: dict[str, Any] | None = None,
    scene_values: dict[str, str] | None = None,
) -> Converted:
    if entity.get("class") is not None:
        raise ConversionError("light_device_class")

    # Validate entity-level hidden/mode semantics without adding a device_class.
    _entity_metadata(entity, {})
    dps = _light_dps(entity)

    switch = dps.get("switch")
    if switch is None:
        # LocalTuya's light entity currently requires a writable primary power DP.
        raise ConversionError("light_missing_switch")
    _check_common_dp_semantics(switch, writable=True)
    if _dp_type(switch) != "boolean":
        raise ConversionError("light_switch_non_boolean")
    _identity_boolean_mapping(switch, "light_switch_mapping")

    config: dict[str, Any] = {
        "id": _dp_id(switch),
        "platform": "light",
        "music_mode": False,
    }
    required: set[int] = set()
    optional: set[int] = set()
    _merge_membership(required, optional, switch)

    effect = dps.get("effect")
    if effect is not None:
        _check_common_dp_semantics(effect, writable=True)
        if _dp_type(effect) != "string":
            raise ConversionError("light_effect_type")
        rules = _mapping_rules(effect)
        if not rules:
            raise ConversionError("light_effect_missing_mapping")

        effect_values: dict[str, str] = {}
        raw_effects: set[str] = set()
        for rule in rules:
            if set(rule) - {"dps_val", "value", "hidden"}:
                raise ConversionError("light_effect_mapping")
            if rule.get("hidden") is True:
                raise ConversionError("light_effect_hidden")
            raw = rule.get("dps_val")
            friendly = rule.get("value")
            if (
                not isinstance(raw, str)
                or not raw
                or not isinstance(friendly, str)
                or not friendly.strip()
            ):
                raise ConversionError("light_effect_non_string_mapping")
            friendly = friendly.strip()
            if raw in raw_effects or friendly in effect_values:
                raise ConversionError("light_effect_duplicate")
            raw_effects.add(raw)
            effect_values[friendly] = raw

        config["effect"] = _dp_id(effect)
        config["effect_values"] = effect_values
        _merge_membership(required, optional, effect)

    configured_scene_values = dict(scene_values or {})
    if scene_dp is not None:
        _check_common_dp_semantics(scene_dp, writable=True)
        if _dp_type(scene_dp) != "string" or not configured_scene_values:
            raise ConversionError("light_scene_data_context")
        config["scene"] = _dp_id(scene_dp)
        _merge_membership(required, optional, scene_dp)

    brightness = dps.get("brightness")
    if brightness is not None:
        _check_common_dp_semantics(brightness, writable=True)
        if _dp_type(brightness) != "integer":
            raise ConversionError("light_brightness_type")
        if _mapping_rules(brightness):
            raise ConversionError("light_brightness_mapping")
        if brightness.get("step") not in (None, 1):
            raise ConversionError("light_brightness_step")
        minimum, maximum = _raw_integer_range(brightness, "light_brightness")
        config.update(
            {
                "brightness": _dp_id(brightness),
                "brightness_lower": minimum,
                "brightness_upper": maximum,
            }
        )
        _merge_membership(required, optional, brightness)

    color_temp = dps.get("color_temp")
    if color_temp is not None:
        _check_common_dp_semantics(color_temp, writable=True)
        if _dp_type(color_temp) != "integer":
            raise ConversionError("light_color_temp_type")
        raw_min, raw_max = _raw_integer_range(color_temp, "light_color_temp")
        if raw_min != 0:
            raise ConversionError("light_color_temp_nonzero_min")

        rules = _mapping_rules(color_temp)
        if len(rules) != 1:
            raise ConversionError("light_color_temp_mapping")
        rule = rules[0]
        if set(rule) - {"target_range", "invert", "step"}:
            raise ConversionError("light_color_temp_mapping")
        if rule.get("step") not in (None, 1):
            raise ConversionError("light_color_temp_step")
        invert = rule.get("invert", False)
        if not isinstance(invert, bool):
            raise ConversionError("light_color_temp_invert")
        target = rule.get("target_range")
        if not isinstance(target, dict) or set(target) != {"min", "max"}:
            raise ConversionError("light_color_temp_target_range")
        target_min = target["min"]
        target_max = target["max"]
        if (
            isinstance(target_min, bool)
            or isinstance(target_max, bool)
            or not isinstance(target_min, (int, float))
            or not isinstance(target_max, (int, float))
            or int(target_min) != target_min
            or int(target_max) != target_max
        ):
            raise ConversionError("light_color_temp_target_range")
        target_min = int(target_min)
        target_max = int(target_max)
        if not (1500 <= target_min < target_max <= 8000):
            raise ConversionError("light_color_temp_target_range")

        _configure_light_scale(
            config,
            minimum=0,
            maximum=raw_max,
            reason="light_color_temp",
            require_lower=False,
        )
        config.update(
            {
                "color_temp": _dp_id(color_temp),
                "color_temp_min_kelvin": target_min,
                "color_temp_max_kelvin": target_max,
                "color_temp_reverse": invert,
            }
        )
        _merge_membership(required, optional, color_temp)

    rgbhsv = dps.get("rgbhsv")
    if rgbhsv is not None:
        _check_common_dp_semantics(rgbhsv, writable=True)
        if _dp_type(rgbhsv) != "hex":
            raise ConversionError("light_rgbhsv_type")
        if _mapping_rules(rgbhsv):
            raise ConversionError("light_rgbhsv_mapping")
        if rgbhsv.get("endianness") not in (None, "big"):
            raise ConversionError("light_rgbhsv_endianness")
        for unsupported in ("mask", "mask_signed", "precision", "step"):
            if rgbhsv.get(unsupported) is not None:
                raise ConversionError(f"light_rgbhsv_{unsupported}")

        fmt = rgbhsv.get("format")
        if not isinstance(fmt, list) or len(fmt) != 3:
            raise ConversionError("light_rgbhsv_format")
        expected = (("h", 0, 360), ("s", 0, 1000), ("v", None, None))
        v_min = v_max = None
        for item, (name, exact_min, exact_max) in zip(fmt, expected, strict=True):
            if not isinstance(item, dict):
                raise ConversionError("light_rgbhsv_format")
            if set(item) != {"name", "bytes", "range"}:
                raise ConversionError("light_rgbhsv_format")
            if item.get("name") != name or item.get("bytes") != 2:
                raise ConversionError("light_rgbhsv_format")
            value_range = item.get("range")
            if not isinstance(value_range, dict) or set(value_range) != {"min", "max"}:
                raise ConversionError("light_rgbhsv_format")
            minimum = value_range["min"]
            maximum = value_range["max"]
            if (
                isinstance(minimum, bool)
                or isinstance(maximum, bool)
                or not isinstance(minimum, (int, float))
                or not isinstance(maximum, (int, float))
                or int(minimum) != minimum
                or int(maximum) != maximum
            ):
                raise ConversionError("light_rgbhsv_format")
            minimum = int(minimum)
            maximum = int(maximum)
            if name != "v":
                if minimum != exact_min or maximum != exact_max:
                    raise ConversionError("light_rgbhsv_format")
            else:
                if minimum < 0 or maximum <= minimum or maximum > 10000:
                    raise ConversionError("light_rgbhsv_format")
                v_min, v_max = minimum, maximum

        assert v_min is not None and v_max is not None
        _configure_light_scale(
            config,
            minimum=v_min,
            maximum=v_max,
            reason="light_rgbhsv",
            require_lower=True,
        )
        config["color"] = _dp_id(rgbhsv)
        _merge_membership(required, optional, rgbhsv)

    color_mode = dps.get("color_mode")
    if color_mode is not None:
        _check_common_dp_semantics(color_mode, writable=True)
        if _dp_type(color_mode) != "string":
            raise ConversionError("light_color_mode_type")
        rules = _mapping_rules(color_mode)
        if not rules:
            raise ConversionError("light_color_mode_mapping")

        observed: dict[str, str] = {}
        for rule in rules:
            if set(rule) - {"dps_val", "value", "hidden"}:
                raise ConversionError("light_color_mode_mapping")
            if rule.get("hidden") is True:
                raise ConversionError("light_color_mode_hidden")
            raw = rule.get("dps_val")
            value = rule.get("value")
            if not isinstance(raw, str) or not isinstance(value, str):
                raise ConversionError("light_color_mode_mapping")

            if raw in observed or value in observed.values():
                raise ConversionError("light_color_mode_duplicate")

            if value in {"hs", "color_temp"}:
                expected_raw = "colour" if value == "hs" else "white"
                if raw != expected_raw:
                    raise ConversionError("light_color_mode_raw_value")
                observed[raw] = value
                continue

            if raw.startswith("scene_"):
                friendly = value.strip()
                if not friendly or friendly in configured_scene_values:
                    raise ConversionError("light_color_mode_duplicate")
                configured_scene_values[friendly] = raw
                observed[raw] = value
                continue

            if raw == "music" and value.strip().casefold() == "music":
                config["music_mode"] = True
                observed[raw] = value
                continue

            if raw == "scene":
                if scene_dp is None or not configured_scene_values:
                    raise ConversionError("light_scene_data_required")
                observed[raw] = value
                continue

            raise ConversionError("light_color_mode_effects")

        if configured_scene_values:
            config["scene_values"] = configured_scene_values

        if "colour" in observed and rgbhsv is None:
            raise ConversionError("light_color_mode_missing_rgbhsv")
        if "white" in observed and color_temp is None:
            raise ConversionError("light_color_mode_missing_color_temp")
        if rgbhsv is not None and "colour" not in observed:
            raise ConversionError("light_color_mode_missing_hs")
        if color_temp is not None and "white" not in observed:
            raise ConversionError("light_color_mode_missing_cct")

        config["color_mode"] = _dp_id(color_mode)
        _merge_membership(required, optional, color_mode)
    elif rgbhsv is not None and color_temp is not None:
        # With both capabilities present LocalTuya needs the raw work-mode DP to
        # distinguish white/CCT from HS state and to switch modes on writes.
        raise ConversionError("light_missing_color_mode")

    return {"platform": "light", "config": config}, required, optional


_CONVERTERS: dict[str, Converter] = {
    "binary_sensor": _convert_binary_sensor,
    "light": _convert_light,
    "number": _convert_number,
    "select": _convert_select,
    "sensor": _convert_sensor,
    "switch": _convert_switch,
}


def _canonical_mapping_id(mapping_without_id: dict[str, Any]) -> str:
    canonical = json.dumps(
        mapping_without_id,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:10]
    primary = mapping_without_id["match"]["product_ids"][0]
    safe = "".join(
        char if char.isalnum() or char in "._-" else "-" for char in primary
    ).strip("-") or "tuya-product"
    return f"{safe}-{digest}"


def convert_profile(
    profile: Any,
    *,
    source_file: str,
    revision: str | None = None,
) -> dict[str, Any]:
    """Convert one fully representable Tuya Local profile to Catalog V2."""
    if not isinstance(profile, dict):
        raise ConversionError("profile_not_object")

    product_ids = _product_ids(profile)
    if not product_ids:
        raise ConversionError("missing_product_id")

    entities = profile.get("entities")
    if not isinstance(entities, list) or not entities:
        raise ConversionError("missing_entities")

    converted_entities: list[dict[str, Any]] = []
    required_dps: set[int] = set()
    optional_dps: set[int] = set()

    scene_context = _find_light_scene_context(entities)
    consumed_entities: set[int] = set()
    if scene_context is not None:
        consumed_entities.add(scene_context[3])

    for index, entity in enumerate(entities):
        if index in consumed_entities:
            continue
        if not isinstance(entity, dict):
            raise ConversionError("invalid_entity")
        platform = entity.get("entity")
        if platform not in SUPPORTED_PLATFORMS:
            raise ConversionError(f"unsupported_platform:{platform}")

        if (
            platform == "light"
            and scene_context is not None
            and scene_context[0] == index
        ):
            converted, entity_required, entity_optional = _convert_light(
                entity,
                scene_dp=scene_context[1],
                scene_values=scene_context[2],
            )
        else:
            converted, entity_required, entity_optional = _CONVERTERS[platform](
                entity
            )
        converted_entities.append(converted)
        required_dps.update(entity_required)
        optional_dps.update(entity_optional)

    if required_dps & optional_dps:
        raise ConversionError("required_optional_overlap")
    if not required_dps:
        # A mapping made entirely from optional entities has no safe fingerprint
        # anchor and could match unrelated firmware variants too broadly.
        raise ConversionError("no_required_dps")

    provenance: dict[str, str] = {
        "source": SOURCE_REPOSITORY,
        "path": f"custom_components/tuya_local/devices/{source_file}",
        "license": SOURCE_LICENSE,
    }
    if revision:
        provenance["revision"] = revision

    mapping_without_id = {
        "confidence": "experimental",
        "match": {
            "product_ids": product_ids,
            "category": None,
            "required_dps": sorted(required_dps),
            "optional_dps": sorted(optional_dps),
        },
        "entities": converted_entities,
        "provenance": provenance,
    }

    return {
        "id": _canonical_mapping_id(mapping_without_id),
        **mapping_without_id,
    }


def analyze_source(
    source: Path,
    *,
    revision: str | None = None,
    output_dir: Path | None = None,
) -> tuple[list[ImportResult], list[dict[str, Any]]]:
    """Convert all profiles that pass the lossless subset."""
    devices_dir = _devices_dir(source)
    results: list[ImportResult] = []
    mappings: list[dict[str, Any]] = []

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    for path in sorted(devices_dir.glob("*.yaml")):
        try:
            profile = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as err:
            results.append(
                ImportResult(
                    file=path.name,
                    name="",
                    status="skipped",
                    mapping_id=None,
                    product_ids=(),
                    platforms=(),
                    reasons=(f"yaml_error:{type(err).__name__}",),
                )
            )
            continue

        profile_dict = profile if isinstance(profile, dict) else {}
        products = tuple(_product_ids(profile_dict))
        platforms = tuple(_platforms(profile_dict))
        name = str(profile_dict.get("name", "")).strip()

        try:
            mapping = convert_profile(
                profile,
                source_file=path.name,
                revision=revision,
            )
        except ConversionError as err:
            results.append(
                ImportResult(
                    file=path.name,
                    name=name,
                    status="skipped",
                    mapping_id=None,
                    product_ids=products,
                    platforms=platforms,
                    reasons=(str(err),),
                )
            )
            continue

        mappings.append(mapping)
        results.append(
            ImportResult(
                file=path.name,
                name=name,
                status="convertible",
                mapping_id=mapping["id"],
                product_ids=products,
                platforms=platforms,
                reasons=(),
            )
        )

        if output_dir is not None:
            payload = {
                "schema_version": 2,
                "mappings": [mapping],
            }
            (output_dir / f"{mapping['id']}.json").write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

    return results, mappings


def build_report(results: list[ImportResult]) -> dict[str, Any]:
    status_counts = Counter(result.status for result in results)
    reason_counts = Counter(
        reason for result in results for reason in result.reasons
    )
    platform_counts = Counter(
        platform
        for result in results
        if result.status == "convertible"
        for platform in result.platforms
    )
    return {
        "source": SOURCE_REPOSITORY,
        "target_schema": 2,
        "profiles": len(results),
        "status_counts": dict(sorted(status_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
        "convertible_platform_counts": dict(sorted(platform_counts.items())),
        "results": [asdict(result) for result in results],
    }


def _print_summary(report: dict[str, Any]) -> None:
    print(f"Profiles analyzed: {report['profiles']}")
    print("Status:")
    for status, count in report["status_counts"].items():
        print(f"  {status}: {count}")

    print("Convertible entity platforms:")
    for platform, count in report["convertible_platform_counts"].items():
        print(f"  {platform}: {count}")

    print("Top skip reasons:")
    ranked = sorted(
        report["reason_counts"].items(),
        key=lambda item: (-item[1], item[0]),
    )
    for reason, count in ranked[:25]:
        print(f"  {reason}: {count}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert lossless static Tuya Local profiles to Catalog V2."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--revision")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--json", type=Path, dest="json_output")
    args = parser.parse_args()

    results, _ = analyze_source(
        args.source,
        revision=args.revision,
        output_dir=args.output_dir,
    )
    report = build_report(results)
    _print_summary(report)

    if args.json_output is not None:
        args.json_output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
