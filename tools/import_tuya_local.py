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
    "button",
    "climate",
    "cover",
    "fan",
    "humidifier",
    "light",
    "lock",
    "number",
    "select",
    "sensor",
    "switch",
    "text",
    "vacuum",
    "valve",
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

    supported = {
        "switch",
        "brightness",
        "color_mode",
        "color_temp",
        "rgbhsv",
        "effect",
        "work_mode",
        "music_data",
        "alt_brightness",
        "app_mode",
        "available",
        "color_addressable",
        "color_data_raw",
        "color_temp_supported",
        "control_data",
        "dreamlight_scene",
        "dreamlight_scene_mode",
        "firmware_version",
        "identity",
        "length_cm",
        "min_brightness",
        "minimum_brightness",
        "mix_rgbcw",
        "power",
        "scene",
        "scene_brightness",
        "scene_data",
        "selected_scene_to_delete",
        "animation_diy",
    "animation_folder",
    "animation_preset",
    "button_setting",
    "color_favorite",
    "color_sync",
    "dreamlight_music_data",
    "dreamlightmic_music_data",
    "flash_scene1",
    "flash_scene2",
    "flash_scene3",
    "flash_scene4",
    "flash_scene_1",
    "flash_scene_2",
    "flash_scene_3",
    "flash_scene_4",
    "mic_music_data",
    "mode",
    "music_devicedata",
    "rhythm_mode",
    "sleep_mode",
    "wakeup_mode",
    "unknown_4",
    "unknown_32",
    "unknown_33",
    "unknown_34",
    "unknown_35",
    "unknown_36",
    "scene_list",
    "splitter_setting",
    "std_switch",
    }
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


LIGHT_RAW_EXTRA_DP_NAMES = {
    "alt_brightness",
    "app_mode",
    "available",
    "color_addressable",
    "color_data_raw",
    "color_temp_supported",
    "control_data",
    "dreamlight_scene",
    "dreamlight_scene_mode",
    "firmware_version",
    "identity",
    "length_cm",
    "min_brightness",
    "minimum_brightness",
    "mix_rgbcw",
    "power",
    "scene",
    "scene_brightness",
    "scene_data",
    "selected_scene_to_delete",
    "animation_diy",
    "animation_folder",
    "animation_preset",
    "button_setting",
    "color_favorite",
    "color_sync",
    "dreamlight_music_data",
    "dreamlightmic_music_data",
    "flash_scene1",
    "flash_scene2",
    "flash_scene3",
    "flash_scene4",
    "flash_scene_1",
    "flash_scene_2",
    "flash_scene_3",
    "flash_scene_4",
    "mic_music_data",
    "mode",
    "music_devicedata",
    "rhythm_mode",
    "sleep_mode",
    "wakeup_mode",
    "unknown_4",
    "unknown_32",
    "unknown_33",
    "unknown_34",
    "unknown_35",
    "unknown_36",
    "scene_list",
    "splitter_setting",
    "std_switch",
}


def _preserve_simple_light_extra_attribute(
    name: str,
    dp: dict[str, Any],
    config: dict[str, Any],
    required: set[int],
    optional: set[int],
) -> None:
    """Preserve one Tuya Local light DP that is only an extra state attribute."""
    _check_common_dp_semantics(dp, writable=False)

    # TuyaLocalEntity._init_end exposes these values through get_value(), which
    # leaves plain string-like DPS unchanged when there is no mapping/mask.
    allowed_types = {"string", "hex", "base64"}
    if name.startswith("unknown_") and name[len("unknown_") :].isdigit():
        allowed_types.add("integer")
    if _dp_type(dp) not in allowed_types:
        raise ConversionError(f"light_extra_attribute_type:{name}")
    if _mapping_rules(dp):
        raise ConversionError(f"light_extra_attribute_mapping:{name}")

    allowed_keys = {
        "id",
        "type",
        "name",
        "optional",
        "readonly",
        "hidden",
        "force",
        "persist",
        "sensitive",
    }
    if set(dp) - allowed_keys:
        raise ConversionError(f"light_extra_attribute_semantics:{name}")

    # Tuya Local explicitly blacklists these names from extra_state_attributes.
    # Keep their DP membership for matching, but do not expose a new HA attr.
    if name not in {"state", "available"}:
        config.setdefault("extra_state_attributes_dps", {})[name] = _dp_id(dp)
    _merge_membership(required, optional, dp)


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

    work_mode = dps.get("work_mode")
    if work_mode is not None:
        _check_common_dp_semantics(work_mode, writable=False)
        if _dp_type(work_mode) != "string":
            raise ConversionError("light_work_mode_type")
        if _mapping_rules(work_mode):
            raise ConversionError("light_work_mode_mapping")
        allowed_work_mode_keys = {
            "id",
            "type",
            "name",
            "optional",
            "readonly",
            "hidden",
            "force",
            "persist",
            "sensitive",
        }
        if set(work_mode) - allowed_work_mode_keys:
            raise ConversionError("light_work_mode_semantics")
        config.setdefault("extra_state_attributes_dps", {})[
            "work_mode"
        ] = _dp_id(work_mode)
        _merge_membership(required, optional, work_mode)

    music_data = dps.get("music_data")
    if music_data is not None:
        _check_common_dp_semantics(music_data, writable=False)
        if _dp_type(music_data) not in {"string", "hex", "base64"}:
            raise ConversionError("light_music_data_type")
        if _mapping_rules(music_data):
            raise ConversionError("light_music_data_mapping")
        allowed_music_data_keys = {
            "id",
            "type",
            "name",
            "optional",
            "readonly",
            "hidden",
            "force",
            "persist",
            "sensitive",
        }
        if set(music_data) - allowed_music_data_keys:
            raise ConversionError("light_music_data_semantics")
        config.setdefault("extra_state_attributes_dps", {})[
            "music_data"
        ] = _dp_id(music_data)
        _merge_membership(required, optional, music_data)

    for extra_name in sorted(LIGHT_RAW_EXTRA_DP_NAMES):
        extra_dp = dps.get(extra_name)
        if extra_dp is not None:
            _preserve_simple_light_extra_attribute(
                extra_name, extra_dp, config, required, optional
            )

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
        brightness_step = 1
        brightness_null_value = None
        rules = _mapping_rules(brightness)
        if rules:
            if len(rules) != 1:
                raise ConversionError("light_brightness_mapping")
            rule = rules[0]
            if set(rule) == {"step"}:
                step = rule.get("step")
                if isinstance(step, bool) or not isinstance(step, int) or step <= 0:
                    raise ConversionError("light_brightness_mapping")
                brightness_step = step
            elif (
                set(rule) == {"dps_val", "value"}
                and rule.get("dps_val") is None
                and rule.get("value") == 0
            ):
                # Exact Tuya Local forward-only brightness fallback observed on
                # XLD-CL002: a missing DP value is presented as brightness 0.
                # Runtime applies this only while reading; writes stay numeric.
                brightness_null_value = 0
            else:
                raise ConversionError("light_brightness_mapping")
        if brightness.get("step") not in (None, 1):
            raise ConversionError("light_brightness_step")
        minimum, maximum = _raw_integer_range(brightness, "light_brightness")
        # Tuya Local applies mapping.step only on writes: step * round(raw / step).
        # Keep the exact raw range for reads and pass the write quantizer to runtime.
        if brightness_step * round(minimum / brightness_step) < minimum:
            raise ConversionError("light_brightness_step_range")
        if brightness_step * round(maximum / brightness_step) > maximum:
            raise ConversionError("light_brightness_step_range")
        config.update(
            {
                "brightness": _dp_id(brightness),
                "brightness_lower": minimum,
                "brightness_upper": maximum,
            }
        )
        if brightness_step != 1:
            config["brightness_step"] = brightness_step
        if brightness_null_value is not None:
            config["brightness_null_value"] = brightness_null_value
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
        if not isinstance(fmt, list):
            raise ConversionError("light_rgbhsv_format")

        if len(fmt) == 6:
            # Tuya's legacy extended color payload is exactly:
            # R(1), G(1), B(1), H(2), S(1), V(1) => 14 hex characters.
            # LocalTuya runtime can encode/decode this losslessly when the
            # catalog marks the RGB-prefixed layout explicitly.
            expected_extended = (
                ("r", 1, 0, 255, False),
                ("g", 1, 0, 255, False),
                ("b", 1, 0, 255, False),
                ("h", 2, 0, 360, True),
                ("s", 1, 0, 255, True),
                ("v", 1, 0, 255, True),
            )
            for item, (name, byte_count, exact_min, exact_max, require_range) in zip(
                fmt, expected_extended, strict=True
            ):
                if not isinstance(item, dict):
                    raise ConversionError("light_rgbhsv_format")
                allowed_keys = {"name", "bytes", "range"}
                if set(item) - allowed_keys:
                    raise ConversionError("light_rgbhsv_format")
                if item.get("name") != name or item.get("bytes") != byte_count:
                    raise ConversionError("light_rgbhsv_format")

                value_range = item.get("range")
                if value_range is None and not require_range:
                    continue
                if (
                    not isinstance(value_range, dict)
                    or set(value_range) != {"min", "max"}
                    or value_range.get("min") != exact_min
                    or value_range.get("max") != exact_max
                ):
                    raise ConversionError("light_rgbhsv_format")

            config["color"] = _dp_id(rgbhsv)
            config["color_rgb_encoding"] = True
            _merge_membership(required, optional, rgbhsv)

        elif len(fmt) == 3:
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
        else:
            raise ConversionError("light_rgbhsv_format")

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

            # Tuya Local permits hidden forward-only mappings that are excluded
            # from reverse mapping/writes. Accept only the exact redundant
            # fallback observed on RGBWW bulbs: null -> color_temp. The visible
            # white -> color_temp mapping remains the writable LocalTuya mode.
            if rule.get("hidden") is True:
                if (
                    rule.get("dps_val") is None
                    and rule.get("value") == "color_temp"
                ):
                    continue
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

            if raw == "white" and value == "white":
                # Dedicated RGBW white mode is distinct from CCT: it uses the
                # standalone brightness DP and has no color-temperature DP.
                # Keep the first importer tranche deliberately strict so a
                # missing optional brightness capability cannot expose a mode
                # that LocalTuya cannot actually control.
                if brightness is None or brightness.get("optional") is True:
                    raise ConversionError("light_color_mode_white_brightness")
                if color_temp is not None:
                    raise ConversionError("light_color_mode_white_with_cct")
                config["white_mode"] = True
                observed[raw] = value
                continue

            if raw == "scene" and scene_dp is not None and configured_scene_values:
                observed[raw] = value
                continue

            if raw.startswith("scene"):
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

            raise ConversionError("light_color_mode_effects")

        if configured_scene_values:
            config["scene_values"] = configured_scene_values

        if "colour" in observed and rgbhsv is None:
            raise ConversionError("light_color_mode_missing_rgbhsv")
        if (
            "white" in observed
            and color_temp is None
            and not config.get("white_mode", False)
        ):
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



def _fan_dps(entity: dict[str, Any]) -> dict[str, dict[str, Any]]:
    dps = entity.get("dps")
    if not isinstance(dps, list) or not dps:
        raise ConversionError("fan_missing_dps")

    supported = {"switch", "preset_mode", "speed", "oscillate", "direction"}
    result: dict[str, dict[str, Any]] = {}
    for dp in dps:
        if not isinstance(dp, dict):
            raise ConversionError("invalid_dp")
        name = dp.get("name")
        if not isinstance(name, str) or not name:
            raise ConversionError("fan_missing_dp_name")
        if name not in supported:
            raise ConversionError(f"fan_unsupported_dp:{name}")
        if name in result:
            raise ConversionError(f"fan_duplicate_dp:{name}")
        result[name] = dp
    return result


def _fan_mapping_scalar(value: Any, dp_type: str, reason: str) -> str | int | bool:
    if dp_type == "string":
        if not isinstance(value, str) or not value:
            raise ConversionError(reason)
        return value
    if dp_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConversionError(reason)
        return value
    if dp_type == "boolean":
        if not isinstance(value, bool):
            raise ConversionError(reason)
        return value
    raise ConversionError(reason)


def _fan_static_presets(dp: dict[str, Any]) -> dict[str, str]:
    _check_common_dp_semantics(dp, writable=True)
    if _dp_type(dp) != "string":
        raise ConversionError("fan_preset_type")
    if dp.get("optional") is True:
        raise ConversionError("fan_preset_optional")

    rules = _mapping_rules(dp)
    if not rules:
        raise ConversionError("fan_preset_mapping")

    result: dict[str, str] = {}
    raw_values: set[str] = set()
    for rule in rules:
        if set(rule) - {"dps_val", "value", "hidden"}:
            raise ConversionError("fan_preset_mapping")
        if rule.get("hidden") is True:
            raise ConversionError("fan_preset_hidden")
        raw = rule.get("dps_val")
        friendly = rule.get("value")
        if (
            not isinstance(raw, str)
            or not raw
            or not isinstance(friendly, str)
            or not friendly.strip()
        ):
            raise ConversionError("fan_preset_mapping")
        friendly = friendly.strip()
        if friendly in result or raw in raw_values:
            raise ConversionError("fan_preset_duplicate")
        result[friendly] = raw
        raw_values.add(raw)
    return result


def _fan_boolean_values(dp: dict[str, Any], reason: str) -> tuple[Any, Any]:
    _check_common_dp_semantics(dp, writable=True)
    dp_type = _dp_type(dp)
    rules = _mapping_rules(dp)
    if not rules:
        if dp_type != "boolean":
            raise ConversionError(reason)
        return True, False

    raw_true = raw_false = None
    seen_true = seen_false = False
    for rule in rules:
        if set(rule) - {"dps_val", "value", "hidden"}:
            raise ConversionError(reason)
        if rule.get("hidden") is True or "dps_val" not in rule or "value" not in rule:
            raise ConversionError(reason)
        value = rule["value"]
        if not isinstance(value, bool):
            raise ConversionError(reason)
        raw = _fan_mapping_scalar(rule["dps_val"], dp_type, reason)
        if value:
            if seen_true:
                raise ConversionError(reason)
            seen_true = True
            raw_true = raw
        else:
            if seen_false:
                raise ConversionError(reason)
            seen_false = True
            raw_false = raw
    if not seen_true or not seen_false or raw_true == raw_false:
        raise ConversionError(reason)
    return raw_true, raw_false


def _fan_speed_config(dp: dict[str, Any], config: dict[str, Any]) -> None:
    _check_common_dp_semantics(dp, writable=True)
    dp_type = _dp_type(dp)
    rules = _mapping_rules(dp)
    dp_id = _dp_id(dp)

    if not rules:
        if dp_type != "integer":
            raise ConversionError("fan_speed_type")
        minimum, maximum = _raw_integer_range(dp, "fan_speed")
        if dp.get("step") not in (None, 1):
            raise ConversionError("fan_speed_step")
        active_minimum = max(1, minimum)
        if active_minimum >= maximum:
            raise ConversionError("fan_speed_range")
        config.update({
            "fan_speed_control": dp_id,
            "fan_speed_min": active_minimum,
            "fan_speed_max": maximum,
            "fan_dps_type": "int",
        })
        return

    if dp_type not in {"string", "integer"}:
        raise ConversionError("fan_speed_type")

    mapped: list[tuple[int, str | int]] = []
    raw_seen: set[str | int] = set()
    percentage_seen: set[int] = set()
    for rule in rules:
        if set(rule) - {"dps_val", "value", "hidden"}:
            raise ConversionError("fan_speed_mapping")
        if rule.get("hidden") is True or "dps_val" not in rule or "value" not in rule:
            raise ConversionError("fan_speed_mapping")
        raw = _fan_mapping_scalar(rule["dps_val"], dp_type, "fan_speed_mapping")
        value = rule["value"]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConversionError("fan_speed_mapping")
        if int(value) != value:
            raise ConversionError("fan_speed_mapping")
        percentage = int(value)
        if not 1 <= percentage <= 100:
            raise ConversionError("fan_speed_mapping")
        if raw in raw_seen or percentage in percentage_seen:
            raise ConversionError("fan_speed_duplicate")
        raw_seen.add(raw)
        percentage_seen.add(percentage)
        mapped.append((percentage, raw))

    mapped.sort(key=lambda item: item[0])
    count = len(mapped)
    if count < 2:
        raise ConversionError("fan_speed_mapping")
    expected = [round((index + 1) * 100 / count) for index in range(count)]
    if [percentage for percentage, _ in mapped] != expected:
        raise ConversionError("fan_speed_percentages")

    raw_values = [str(raw) for _, raw in mapped]
    if any(not raw or "," in raw for raw in raw_values):
        raise ConversionError("fan_speed_raw_value")
    config.update({
        "fan_speed_control": dp_id,
        "fan_speed_ordered_list": ",".join(raw_values),
        "fan_dps_type": "int" if dp_type == "integer" else "str",
    })


def _fan_direction_config(dp: dict[str, Any], config: dict[str, Any]) -> None:
    _check_common_dp_semantics(dp, writable=True)
    dp_type = _dp_type(dp)
    rules = _mapping_rules(dp)
    if not rules:
        if dp_type != "string":
            raise ConversionError("fan_direction_mapping")
        forward, reverse = "forward", "reverse"
    else:
        values: dict[str, Any] = {}
        raw_seen: set[Any] = set()
        for rule in rules:
            if set(rule) - {"dps_val", "value", "hidden"}:
                raise ConversionError("fan_direction_mapping")
            if rule.get("hidden") is True or "dps_val" not in rule or "value" not in rule:
                raise ConversionError("fan_direction_mapping")
            friendly = rule["value"]
            if friendly not in {"forward", "reverse"} or friendly in values:
                raise ConversionError("fan_direction_mapping")
            raw = _fan_mapping_scalar(rule["dps_val"], dp_type, "fan_direction_mapping")
            if raw in raw_seen:
                raise ConversionError("fan_direction_mapping")
            values[friendly] = raw
            raw_seen.add(raw)
        if set(values) != {"forward", "reverse"}:
            raise ConversionError("fan_direction_mapping")
        forward, reverse = values["forward"], values["reverse"]

    config.update({
        "fan_direction": _dp_id(dp),
        "fan_direction_forward": forward,
        "fan_direction_reverse": reverse,
    })


def _convert_fan(entity: dict[str, Any]) -> Converted:
    if entity.get("class") is not None:
        raise ConversionError("fan_device_class")
    _entity_metadata(entity, {})
    dps = _fan_dps(entity)

    switch = dps.get("switch")
    if switch is None:
        raise ConversionError("fan_missing_switch")
    _check_common_dp_semantics(switch, writable=True)
    if _dp_type(switch) != "boolean":
        raise ConversionError("fan_switch_type")
    _identity_boolean_mapping(switch, "fan_switch_mapping")

    config: dict[str, Any] = {"id": _dp_id(switch), "platform": "fan"}
    required: set[int] = set()
    optional: set[int] = set()
    _merge_membership(required, optional, switch)

    speed = dps.get("speed")
    if speed is not None:
        _fan_speed_config(speed, config)
        _merge_membership(required, optional, speed)

    preset = dps.get("preset_mode")
    if preset is not None:
        config["fan_preset_dp"] = _dp_id(preset)
        config["fan_preset_values"] = _fan_static_presets(preset)
        _merge_membership(required, optional, preset)

    oscillate = dps.get("oscillate")
    if oscillate is not None:
        raw_on, raw_off = _fan_boolean_values(oscillate, "fan_oscillate_mapping")
        config["fan_oscillating_control"] = _dp_id(oscillate)
        if _dp_type(oscillate) != "boolean" or raw_on is not True or raw_off is not False:
            config["fan_oscillating_on"] = raw_on
            config["fan_oscillating_off"] = raw_off
        _merge_membership(required, optional, oscillate)

    direction = dps.get("direction")
    if direction is not None:
        _fan_direction_config(direction, config)
        _merge_membership(required, optional, direction)

    return {"platform": "fan", "config": config}, required, optional



HVAC_MODE_VALUES = {"off", "heat", "cool", "auto", "dry", "fan_only", "heat_cool"}
HVAC_ACTION_VALUES = {"off", "heating", "cooling", "drying", "fan", "idle"}
TEMP_UNITS = {"celsius", "fahrenheit"}


def _climate_dps(entity: dict[str, Any]) -> dict[str, dict[str, Any]]:
    dps = entity.get("dps")
    if not isinstance(dps, list) or not dps:
        raise ConversionError("climate_missing_dps")
    result: dict[str, dict[str, Any]] = {}
    for dp in dps:
        if not isinstance(dp, dict):
            raise ConversionError("invalid_dp")
        name = dp.get("name")
        if not isinstance(name, str) or not name:
            raise ConversionError("climate_missing_dp_name")
        if name in result:
            raise ConversionError(f"climate_duplicate_dp:{name}")
        result[name] = dp
    return result


def _simple_scalar(value: Any, dp_type: str, reason: str) -> str | int | bool:
    if dp_type == "string":
        if not isinstance(value, str):
            raise ConversionError(reason)
        return value
    if dp_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConversionError(reason)
        return value
    if dp_type == "boolean":
        if not isinstance(value, bool):
            raise ConversionError(reason)
        return value
    raise ConversionError(reason)


def _climate_static_values(
    dp: dict[str, Any],
    *,
    reason: str,
    friendly_allowed: set[str] | None = None,
    friendly_strings: bool = True,
) -> dict[str, str | int | bool]:
    _check_common_dp_semantics(dp, writable=True)
    dp_type = _dp_type(dp)
    if dp_type not in {"string", "integer", "boolean"}:
        raise ConversionError(f"{reason}_type")
    rules = _mapping_rules(dp)
    if not rules:
        if dp_type == "boolean" and friendly_allowed == HVAC_MODE_VALUES:
            return {"heat": True, "off": False}
        raise ConversionError(f"{reason}_mapping")
    result: dict[str, str | int | bool] = {}
    raw_seen: list[str | int | bool] = []
    for rule in rules:
        if set(rule) - {"dps_val", "value", "hidden"}:
            raise ConversionError(f"{reason}_mapping")
        if rule.get("hidden") is True or "dps_val" not in rule or "value" not in rule:
            raise ConversionError(f"{reason}_mapping")
        raw = _simple_scalar(rule["dps_val"], dp_type, f"{reason}_mapping")
        friendly = rule["value"]
        if friendly_strings:
            if not isinstance(friendly, str) or not friendly.strip():
                raise ConversionError(f"{reason}_mapping")
            friendly = friendly.strip()
        else:
            friendly = str(friendly)
        if friendly_allowed is not None and friendly not in friendly_allowed:
            raise ConversionError(f"{reason}_friendly")
        if friendly in result or any(raw == seen for seen in raw_seen):
            raise ConversionError(f"{reason}_duplicate")
        result[friendly] = raw
        raw_seen.append(raw)
    return result


def _climate_numeric(
    dp: dict[str, Any],
    *,
    writable: bool,
    reason: str,
    require_range: bool,
) -> tuple[float, float | None, float | None, float]:
    _check_common_dp_semantics(dp, writable=writable)
    if _dp_type(dp) != "integer":
        raise ConversionError(f"{reason}_type")
    rules = _mapping_rules(dp)
    rule: dict[str, Any] = {}
    if rules:
        if len(rules) != 1 or "dps_val" in rules[0]:
            raise ConversionError(f"{reason}_mapping")
        rule = rules[0]
        if set(rule) - {"scale", "step", "range"}:
            raise ConversionError(f"{reason}_mapping")

    divisor = rule.get("scale", 1)
    if isinstance(divisor, bool):
        raise ConversionError(f"{reason}_scale")
    try:
        divisor = float(divisor)
    except (TypeError, ValueError) as err:
        raise ConversionError(f"{reason}_scale") from err
    if not math.isfinite(divisor) or divisor <= 0:
        raise ConversionError(f"{reason}_scale")
    precision = 1.0 / divisor

    raw_range = rule.get("range", dp.get("range"))
    minimum = maximum = None
    if raw_range is not None:
        if not isinstance(raw_range, dict) or "min" not in raw_range or "max" not in raw_range:
            raise ConversionError(f"{reason}_range")
        minimum = _range_value(raw_range["min"], precision, f"{reason}_range")
        maximum = _range_value(raw_range["max"], precision, f"{reason}_range")
        if maximum < minimum:
            raise ConversionError(f"{reason}_range")
    elif require_range:
        raise ConversionError(f"{reason}_range")

    raw_step = rule.get("step", dp.get("step", 1))
    step = _range_value(raw_step, precision, f"{reason}_step")
    if step <= 0:
        raise ConversionError(f"{reason}_step")
    return precision, minimum, maximum, step


def _merge_climate_dp(required: set[int], optional: set[int], dp: dict[str, Any]) -> None:
    _merge_membership(required, optional, dp)


def _preserve_climate_extra(
    name: str,
    dp: dict[str, Any],
    config: dict[str, Any],
    required: set[int],
    optional: set[int],
) -> None:
    # Hidden Tuya Local DPS affect matching/conditions but are not HA attributes.
    if dp.get("force") is True or dp.get("persist") is False or dp.get("sensitive") is True:
        raise ConversionError(f"climate_extra_semantics:{name}")
    if dp.get("readonly") not in (None, False, True):
        raise ConversionError(f"climate_extra_semantics:{name}")
    if _mapping_rules(dp):
        raise ConversionError(f"climate_extra_mapping:{name}")
    allowed = {
        "id", "type", "name", "optional", "readonly", "hidden", "force",
        "persist", "sensitive", "unit", "class", "category",
    }
    if set(dp) - allowed:
        raise ConversionError(f"climate_extra_semantics:{name}")
    if dp.get("hidden") is not True and name not in {"state", "available"}:
        config.setdefault("extra_state_attributes_dps", {})[name] = _dp_id(dp)
    _merge_climate_dp(required, optional, dp)


def _convert_climate(entity: dict[str, Any]) -> Converted:
    if entity.get("class") is not None:
        raise ConversionError("climate_device_class")
    _entity_metadata(entity, {})
    dps = _climate_dps(entity)

    hvac = dps.get("hvac_mode")
    if hvac is None:
        raise ConversionError("climate_missing_hvac_mode")
    hvac_values = _climate_static_values(
        hvac, reason="climate_hvac_mode", friendly_allowed=HVAC_MODE_VALUES
    )
    if "off" not in hvac_values:
        raise ConversionError("climate_hvac_mode_missing_off")
    if len(hvac_values) < 2:
        raise ConversionError("climate_hvac_mode_no_active_mode")

    config: dict[str, Any] = {
        "id": _dp_id(hvac),
        "platform": "climate",
        "hvac_mode_dp": _dp_id(hvac),
        "hvac_mode_values": hvac_values,
    }
    required: set[int] = set()
    optional: set[int] = set()
    _merge_climate_dp(required, optional, hvac)

    target = dps.get("temperature")
    if target is not None:
        precision, minimum, maximum, step = _climate_numeric(
            target, writable=True, reason="climate_temperature", require_range=True
        )
        config["target_temperature_dp"] = _dp_id(target)
        config["target_precision"] = precision
        config["temperature_step"] = step
        config["min_temperature_const"] = minimum
        config["max_temperature_const"] = maximum
        _merge_climate_dp(required, optional, target)

    current = dps.get("current_temperature")
    if current is not None:
        precision, _, _, _ = _climate_numeric(
            current, writable=False, reason="climate_current_temperature", require_range=False
        )
        config["current_temperature_dp"] = _dp_id(current)
        config["precision"] = precision
        _merge_climate_dp(required, optional, current)

    low = dps.get("target_temp_low")
    high = dps.get("target_temp_high")
    if (low is None) != (high is None):
        raise ConversionError("climate_target_range_incomplete")
    if low is not None and high is not None:
        low_precision, low_min, _, low_step = _climate_numeric(
            low, writable=True, reason="climate_target_low", require_range=True
        )
        high_precision, _, high_max, high_step = _climate_numeric(
            high, writable=True, reason="climate_target_high", require_range=True
        )
        if not math.isclose(low_step, high_step, rel_tol=0, abs_tol=1e-9):
            raise ConversionError("climate_target_range_step")
        config.update({
            "target_temperature_low_dp": _dp_id(low),
            "target_temperature_high_dp": _dp_id(high),
            "target_temperature_low_precision": low_precision,
            "target_temperature_high_precision": high_precision,
            "temperature_step": low_step,
        })
        if target is None:
            config["min_temperature_const"] = low_min
            config["max_temperature_const"] = high_max
        _merge_climate_dp(required, optional, low)
        _merge_climate_dp(required, optional, high)

    target_humidity = dps.get("humidity")
    if target_humidity is not None:
        precision, minimum, maximum, _ = _climate_numeric(
            target_humidity, writable=True, reason="climate_humidity", require_range=True
        )
        config.update({
            "target_humidity_dp": _dp_id(target_humidity),
            "target_humidity_precision": precision,
            "min_humidity_const": minimum,
            "max_humidity_const": maximum,
        })
        _merge_climate_dp(required, optional, target_humidity)

    current_humidity = dps.get("current_humidity")
    if current_humidity is not None:
        precision, _, _, _ = _climate_numeric(
            current_humidity, writable=False, reason="climate_current_humidity", require_range=False
        )
        config.update({
            "current_humidity_dp": _dp_id(current_humidity),
            "current_humidity_precision": precision,
        })
        _merge_climate_dp(required, optional, current_humidity)

    mapped = {
        "preset_mode": ("preset_dp", "preset_values", "climate_preset", None),
        "fan_mode": ("hvac_fan_mode_dp", "hvac_fan_mode_values", "climate_fan_mode", None),
        "swing_mode": ("hvac_swing_mode_dp", "hvac_swing_mode_values", "climate_swing_mode", None),
        "swing_horizontal_mode": (
            "hvac_swing_horizontal_mode_dp", "hvac_swing_horizontal_mode_values",
            "climate_swing_horizontal_mode", None,
        ),
        "hvac_action": ("hvac_action_dp", "hvac_action_values", "climate_hvac_action", HVAC_ACTION_VALUES),
        "temperature_unit": ("temperature_unit_dp", "temperature_unit_values", "climate_temperature_unit", TEMP_UNITS),
    }
    consumed = {
        "hvac_mode", "temperature", "current_temperature", "target_temp_low",
        "target_temp_high", "humidity", "current_humidity",
    }
    for name, (dp_key, values_key, reason, allowed) in mapped.items():
        dp = dps.get(name)
        if dp is None:
            continue
        values = _climate_static_values(dp, reason=reason, friendly_allowed=allowed)
        config[dp_key] = _dp_id(dp)
        config[values_key] = values
        _merge_climate_dp(required, optional, dp)
        consumed.add(name)

    # Device-reported min/max temperatures are preserved only when they are raw
    # integers. Scaled or mapped variants require per-DP precision support.
    for name, key in (("min_temperature", "min_temperature_dp"), ("max_temperature", "max_temperature_dp")):
        dp = dps.get(name)
        if dp is None:
            continue
        _check_common_dp_semantics(dp, writable=False)
        if _dp_type(dp) != "integer" or _mapping_rules(dp):
            raise ConversionError(f"climate_{name}_semantics")
        config[key] = _dp_id(dp)
        _merge_climate_dp(required, optional, dp)
        consumed.add(name)

    # Do not expose a dynamic unit DP and a fixed entity-level unit at once.
    if "temperature_unit" not in consumed:
        units = set()
        for candidate in (target, current, low, high):
            if candidate is not None and candidate.get("unit") is not None:
                unit = candidate.get("unit")
                if unit == "C":
                    units.add("celsius")
                elif unit == "F":
                    units.add("fahrenheit")
                else:
                    raise ConversionError("climate_temperature_unit")
        if len(units) > 1:
            raise ConversionError("climate_temperature_unit_mismatch")
        if units:
            config["temperature_unit"] = next(iter(units))

    for name, dp in dps.items():
        if name in consumed:
            continue
        _preserve_climate_extra(name, dp, config, required, optional)

    return {"platform": "climate", "config": config}, required, optional


COVER_ACTION_SEMANTICS = {"opening", "closing", "opened", "closed"}
COVER_COMMAND_SEMANTICS = {"open", "close", "stop"}
COVER_OPEN_SEMANTICS = {"open", "closed"}


def _cover_dps(entity: dict[str, Any]) -> dict[str, dict[str, Any]]:
    dps = entity.get("dps")
    if not isinstance(dps, list) or not dps:
        raise ConversionError("cover_missing_dps")
    result: dict[str, dict[str, Any]] = {}
    for dp in dps:
        if not isinstance(dp, dict):
            raise ConversionError("invalid_dp")
        name = dp.get("name")
        if not isinstance(name, str) or not name:
            raise ConversionError("cover_missing_dp_name")
        if name in result:
            raise ConversionError(f"cover_duplicate_dp:{name}")
        result[name] = dp
    return result


def _cover_raw_scalar(value: Any, dp_type: str, reason: str) -> str | int | bool:
    if dp_type == "string":
        if not isinstance(value, str):
            raise ConversionError(reason)
        return value
    if dp_type in {"integer", "bitfield"}:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConversionError(reason)
        return value
    if dp_type == "boolean":
        if not isinstance(value, bool):
            raise ConversionError(reason)
        return value
    raise ConversionError(reason)


def _cover_static_values(
    dp: dict[str, Any],
    *,
    reason: str,
    allowed: set[str],
    writable: bool,
    identity_strings: bool = False,
    direct_boolean: bool = False,
) -> dict[str, str | int | bool]:
    _check_common_dp_semantics(dp, writable=writable)
    dp_type = _dp_type(dp)
    if dp_type not in {"string", "integer", "boolean", "bitfield"}:
        raise ConversionError(f"{reason}_type")
    rules = _mapping_rules(dp)
    if not rules:
        if identity_strings and dp_type == "string":
            return {name: name for name in sorted(allowed)}
        if direct_boolean and dp_type == "boolean" and allowed == COVER_OPEN_SEMANTICS:
            return {"open": True, "closed": False}
        raise ConversionError(f"{reason}_mapping")

    result: dict[str, str | int | bool] = {}
    raw_seen: list[str | int | bool] = []
    for rule in rules:
        if set(rule) - {"dps_val", "value", "hidden"}:
            raise ConversionError(f"{reason}_mapping")
        if "dps_val" not in rule or "value" not in rule:
            raise ConversionError(f"{reason}_mapping")
        if writable and rule.get("hidden") is True:
            # Hidden Tuya Local mappings are forward-only and must not become
            # writable Home Assistant commands.
            continue
        friendly = rule["value"]
        if not isinstance(friendly, str) or friendly not in allowed:
            raise ConversionError(f"{reason}_friendly")
        raw = _cover_raw_scalar(rule["dps_val"], dp_type, f"{reason}_mapping")
        if friendly in result or any(raw == seen for seen in raw_seen):
            raise ConversionError(f"{reason}_duplicate")
        result[friendly] = raw
        raw_seen.append(raw)

    if not result:
        raise ConversionError(f"{reason}_mapping")
    return result


def _cover_position_semantics(
    dp: dict[str, Any], *, writable: bool, reason: str
) -> tuple[float, float, float, bool]:
    _check_common_dp_semantics(dp, writable=writable)
    if _dp_type(dp) != "integer":
        raise ConversionError(f"{reason}_type")

    rules = _mapping_rules(dp)
    rule: dict[str, Any] = {}
    if rules:
        if len(rules) != 1 or "dps_val" in rules[0]:
            raise ConversionError(f"{reason}_mapping")
        rule = rules[0]
        if set(rule) - {"invert", "step"}:
            raise ConversionError(f"{reason}_mapping")

    raw_range = dp.get("range", {"min": 0, "max": 100})
    if not isinstance(raw_range, dict) or "min" not in raw_range or "max" not in raw_range:
        raise ConversionError(f"{reason}_range")
    minimum = _range_value(raw_range["min"], 1.0, f"{reason}_range")
    maximum = _range_value(raw_range["max"], 1.0, f"{reason}_range")
    if maximum <= minimum:
        raise ConversionError(f"{reason}_range")

    step = _range_value(rule.get("step", dp.get("step", 1)), 1.0, f"{reason}_step")
    if step <= 0:
        raise ConversionError(f"{reason}_step")
    inverted = rule.get("invert", False)
    if not isinstance(inverted, bool):
        raise ConversionError(f"{reason}_invert")
    return minimum, maximum, step, inverted


def _preserve_cover_extra(
    name: str,
    dp: dict[str, Any],
    config: dict[str, Any],
    required: set[int],
    optional: set[int],
) -> None:
    if dp.get("force") is True or dp.get("persist") is False or dp.get("sensitive") is True:
        raise ConversionError(f"cover_extra_semantics:{name}")
    if dp.get("readonly") not in (None, False, True):
        raise ConversionError(f"cover_extra_semantics:{name}")
    if _mapping_rules(dp):
        raise ConversionError(f"cover_extra_mapping:{name}")
    if _dp_type(dp) not in {"boolean", "integer", "string", "bitfield", "hex", "base64"}:
        raise ConversionError(f"cover_extra_type:{name}")
    allowed = {
        "id", "type", "name", "optional", "readonly", "hidden", "force",
        "persist", "sensitive", "unit", "class", "category", "range", "step",
    }
    if set(dp) - allowed:
        raise ConversionError(f"cover_extra_semantics:{name}")
    if dp.get("hidden") is not True and name not in {"state", "available"}:
        config.setdefault("extra_state_attributes_dps", {})[name] = _dp_id(dp)
    _merge_membership(required, optional, dp)


def _convert_cover(entity: dict[str, Any]) -> Converted:
    dps = _cover_dps(entity)
    functional = {"control", "position", "current_position", "tilt_position", "action", "open"}
    primary = next((dps[name] for name in ("control", "position", "current_position", "action", "open", "tilt_position") if name in dps), None)
    if primary is None:
        raise ConversionError("cover_missing_functional_dp")

    config: dict[str, Any] = {
        "id": _dp_id(primary),
        "platform": "cover",
        # Presence of this key is intentional. Empty means position-only cover
        # and explicitly disables LocalTuya's legacy on/off/stop fallback.
        "cover_command_values": {},
        "positioning_mode": "none",
    }
    _entity_metadata(entity, config)
    required: set[int] = set()
    optional: set[int] = set()

    control = dps.get("control")
    if control is not None:
        commands = _cover_static_values(
            control,
            reason="cover_control",
            allowed=COVER_COMMAND_SEMANTICS,
            writable=True,
            identity_strings=True,
        )
        config["id"] = _dp_id(control)
        config["cover_command_values"] = commands
        _merge_membership(required, optional, control)

    position = dps.get("position")
    if position is not None:
        minimum, maximum, step, inverted = _cover_position_semantics(
            position, writable=True, reason="cover_position"
        )
        config.update({
            "positioning_mode": "position",
            "set_position_dp": _dp_id(position),
            "set_position_min": minimum,
            "set_position_max": maximum,
            "set_position_step": step,
            "set_position_inverted": inverted,
        })
        _merge_membership(required, optional, position)

    current = dps.get("current_position")
    if current is not None:
        minimum, maximum, _, inverted = _cover_position_semantics(
            current, writable=False, reason="cover_current_position"
        )
        config.update({
            "positioning_mode": "position",
            "current_position_dp": _dp_id(current),
            "current_position_min": minimum,
            "current_position_max": maximum,
            "current_position_inverted": inverted,
        })
        _merge_membership(required, optional, current)

    action = dps.get("action")
    if action is not None:
        config["cover_action_dp"] = _dp_id(action)
        config["cover_action_values"] = _cover_static_values(
            action,
            reason="cover_action",
            allowed=COVER_ACTION_SEMANTICS,
            writable=False,
            identity_strings=True,
        )
        _merge_membership(required, optional, action)

    open_dp = dps.get("open")
    if open_dp is not None:
        config["cover_open_dp"] = _dp_id(open_dp)
        config["cover_open_values"] = _cover_static_values(
            open_dp,
            reason="cover_open",
            allowed=COVER_OPEN_SEMANTICS,
            writable=False,
            direct_boolean=True,
        )
        _merge_membership(required, optional, open_dp)

    tilt = dps.get("tilt_position")
    if tilt is not None:
        minimum, maximum, step, inverted = _cover_position_semantics(
            tilt, writable=True, reason="cover_tilt_position"
        )
        config.update({
            "tilt_position_dp": _dp_id(tilt),
            "tilt_position_min": minimum,
            "tilt_position_max": maximum,
            "tilt_position_step": step,
            "tilt_position_inverted": inverted,
        })
        _merge_membership(required, optional, tilt)

    for name, dp in dps.items():
        if name in functional:
            continue
        _preserve_cover_extra(name, dp, config, required, optional)

    return {"platform": "cover", "config": config}, required, optional

VACUUM_STANDARD_COMMANDS = {"start", "pause", "return_to_base", "clean_spot", "stop"}


def _vacuum_dps(entity: dict[str, Any]) -> dict[str, dict[str, Any]]:
    dps = entity.get("dps")
    if not isinstance(dps, list) or not dps:
        raise ConversionError("vacuum_missing_dps")
    result: dict[str, dict[str, Any]] = {}
    for dp in dps:
        if not isinstance(dp, dict):
            raise ConversionError("invalid_dp")
        name = dp.get("name")
        if not isinstance(name, str) or not name:
            raise ConversionError("vacuum_missing_dp_name")
        if name in result:
            raise ConversionError(f"vacuum_duplicate_dp:{name}")
        result[name] = dp
    return result


def _vacuum_scalar(value: Any, dp_type: str, reason: str) -> str | int | bool:
    if dp_type == "string":
        if not isinstance(value, str):
            raise ConversionError(reason)
        return value
    if dp_type in {"integer", "bitfield"}:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConversionError(reason)
        return value
    if dp_type == "boolean":
        if not isinstance(value, bool):
            raise ConversionError(reason)
        return value
    raise ConversionError(reason)


def _vacuum_static_values(
    dp: dict[str, Any],
    *,
    reason: str,
    writable: bool,
    friendly_strings: bool = True,
) -> dict[str, str | int | bool]:
    _check_common_dp_semantics(dp, writable=writable)
    dp_type = _dp_type(dp)
    if dp_type not in {"string", "integer", "boolean", "bitfield"}:
        raise ConversionError(f"{reason}_type")
    rules = _mapping_rules(dp)
    if not rules:
        raise ConversionError(f"{reason}_mapping")

    result: dict[str, str | int | bool] = {}
    raw_seen: list[str | int | bool] = []
    for rule in rules:
        if set(rule) - {"dps_val", "value", "hidden"}:
            raise ConversionError(f"{reason}_mapping")
        if "dps_val" not in rule or "value" not in rule:
            raise ConversionError(f"{reason}_mapping")
        if writable and rule.get("hidden") is True:
            # Hidden mappings in Tuya Local are forward-only and are not valid
            # reverse/write targets.
            continue
        friendly = rule["value"]
        if friendly_strings:
            if not isinstance(friendly, str) or not friendly:
                raise ConversionError(f"{reason}_friendly")
            key = friendly
        else:
            if not isinstance(friendly, bool):
                raise ConversionError(f"{reason}_friendly")
            key = "on" if friendly else "off"
        raw = _vacuum_scalar(rule["dps_val"], dp_type, f"{reason}_mapping")
        if key in result or any(raw == previous for previous in raw_seen):
            raise ConversionError(f"{reason}_duplicate")
        result[key] = raw
        raw_seen.append(raw)

    if not result:
        raise ConversionError(f"{reason}_mapping")
    return result


def _vacuum_boolean_values(dp: dict[str, Any], reason: str) -> tuple[Any, Any]:
    _check_common_dp_semantics(dp, writable=True)
    dp_type = _dp_type(dp)
    rules = _mapping_rules(dp)
    if not rules:
        if dp_type != "boolean":
            raise ConversionError(f"{reason}_type")
        return True, False
    values = _vacuum_static_values(dp, reason=reason, writable=True, friendly_strings=False)
    if set(values) != {"on", "off"}:
        raise ConversionError(f"{reason}_mapping")
    return values["on"], values["off"]


def _vacuum_trigger_value(dp: dict[str, Any], reason: str) -> Any:
    _check_common_dp_semantics(dp, writable=True)
    if _dp_type(dp) == "boolean" and not _mapping_rules(dp):
        return True
    rules = _mapping_rules(dp)
    if len(rules) != 1:
        raise ConversionError(f"{reason}_mapping")
    rule = rules[0]
    if set(rule) - {"dps_val", "value", "hidden"}:
        raise ConversionError(f"{reason}_mapping")
    if rule.get("hidden") is True or "dps_val" not in rule:
        raise ConversionError(f"{reason}_mapping")
    # Locate is a trigger. Tuya Local writes the logical True value; accept a
    # mapped representation only when the friendly side is exactly true.
    if rule.get("value") is not True:
        raise ConversionError(f"{reason}_mapping")
    return _vacuum_scalar(rule["dps_val"], _dp_type(dp), f"{reason}_mapping")


def _preserve_vacuum_extra(
    name: str,
    dp: dict[str, Any],
    config: dict[str, Any],
    required: set[int],
    optional: set[int],
) -> None:
    if dp.get("force") is True or dp.get("persist") is False or dp.get("sensitive") is True:
        raise ConversionError(f"vacuum_extra_semantics:{name}")
    if dp.get("readonly") not in (None, False, True):
        raise ConversionError(f"vacuum_extra_semantics:{name}")
    if _mapping_rules(dp):
        raise ConversionError(f"vacuum_extra_mapping:{name}")
    if _dp_type(dp) not in {"boolean", "integer", "string", "bitfield", "hex", "base64"}:
        raise ConversionError(f"vacuum_extra_type:{name}")
    allowed = {
        "id", "type", "name", "optional", "readonly", "hidden", "force",
        "persist", "sensitive", "unit", "class", "category", "range", "step",
    }
    if set(dp) - allowed:
        raise ConversionError(f"vacuum_extra_semantics:{name}")
    if dp.get("hidden") is not True and name not in {"state", "available"}:
        config.setdefault("extra_state_attributes_dps", {})[name] = _dp_id(dp)
    _merge_membership(required, optional, dp)


def _convert_vacuum(entity: dict[str, Any]) -> Converted:
    dps = _vacuum_dps(entity)
    status = dps.get("status")
    if status is None:
        raise ConversionError("vacuum_missing_status")
    if status.get("optional") is True:
        raise ConversionError("vacuum_optional_status")
    status_values = _vacuum_static_values(
        status, reason="vacuum_status", writable=False
    )

    config: dict[str, Any] = {
        "id": _dp_id(status),
        "platform": "vacuum",
        "vacuum_status_dp": _dp_id(status),
        "vacuum_status_values": status_values,
    }
    _entity_metadata(entity, config)
    required: set[int] = set()
    optional: set[int] = set()
    _merge_membership(required, optional, status)

    consumed = {"status"}

    command = dps.get("command")
    if command is not None:
        values = _vacuum_static_values(
            command, reason="vacuum_command", writable=True
        )
        config["vacuum_command_dp"] = _dp_id(command)
        config["vacuum_command_values"] = values
        _merge_membership(required, optional, command)
        consumed.add("command")

    direction = dps.get("direction_control")
    if direction is not None:
        values = _vacuum_static_values(
            direction, reason="vacuum_direction", writable=True
        )
        config["vacuum_direction_dp"] = _dp_id(direction)
        config["vacuum_direction_values"] = values
        _merge_membership(required, optional, direction)
        consumed.add("direction_control")

    fan = dps.get("fan_speed")
    if fan is not None:
        values = _vacuum_static_values(
            fan, reason="vacuum_fan_speed", writable=True
        )
        config["fan_speed_dp"] = _dp_id(fan)
        config["vacuum_fan_speed_values"] = values
        _merge_membership(required, optional, fan)
        consumed.add("fan_speed")

    activate = dps.get("activate")
    if activate is not None:
        raw_on, raw_off = _vacuum_boolean_values(activate, "vacuum_activate")
        config["vacuum_activate_dp"] = _dp_id(activate)
        config["vacuum_activate_on"] = raw_on
        config["vacuum_activate_off"] = raw_off
        _merge_membership(required, optional, activate)
        consumed.add("activate")

    power = dps.get("power")
    if power is not None:
        raw_on, raw_off = _vacuum_boolean_values(power, "vacuum_power")
        config["vacuum_power_dp"] = _dp_id(power)
        config["vacuum_power_on"] = raw_on
        config["vacuum_power_off"] = raw_off
        _merge_membership(required, optional, power)
        consumed.add("power")

    locate = dps.get("locate")
    if locate is not None:
        config["locate_dp"] = _dp_id(locate)
        config["vacuum_locate_on"] = _vacuum_trigger_value(locate, "vacuum_locate")
        _merge_membership(required, optional, locate)
        consumed.add("locate")

    error = dps.get("error")
    if error is not None:
        # Tuya Local commonly marks the consumed vacuum error DP hidden.
        # Hidden is safe here because this DP is internal entity state, not a
        # writable option or an extra attribute.
        if error.get("force") is True or error.get("persist") is False or error.get("sensitive") is True:
            raise ConversionError("vacuum_error_semantics")
        if error.get("readonly") not in (None, False, True):
            raise ConversionError("vacuum_error_semantics")
        allowed_error = {
            "id", "type", "name", "optional", "readonly", "hidden", "force",
            "persist", "sensitive", "unit", "class", "category",
        }
        if set(error) - allowed_error:
            raise ConversionError("vacuum_error_semantics")
        if _mapping_rules(error):
            raise ConversionError("vacuum_error_mapping")
        if _dp_type(error) not in {"bitfield", "integer", "boolean", "string"}:
            raise ConversionError("vacuum_error_type")
        config["fault_dp"] = _dp_id(error)
        _merge_membership(required, optional, error)
        consumed.add("error")

    # Some Tuya Local profiles expose pause as a separate raw datapoint but the
    # vacuum entity itself does not consume it; preserve it like _init_end().
    for name, dp in dps.items():
        if name in consumed:
            continue
        _preserve_vacuum_extra(name, dp, config, required, optional)

    return {"platform": "vacuum", "config": config}, required, optional


CORE_PLATFORM_NAMES = {"button", "text", "valve", "lock", "humidifier"}


def _core_named_dps(entity: dict[str, Any], prefix: str) -> dict[str, dict[str, Any]]:
    dps = entity.get("dps")
    if not isinstance(dps, list) or not dps:
        raise ConversionError(f"{prefix}_missing_dps")
    result: dict[str, dict[str, Any]] = {}
    for dp in dps:
        if not isinstance(dp, dict):
            raise ConversionError("invalid_dp")
        name = dp.get("name")
        if not isinstance(name, str) or not name:
            raise ConversionError(f"{prefix}_missing_dp_name")
        if name in result:
            raise ConversionError(f"{prefix}_duplicate_dp:{name}")
        result[name] = dp
    return result


def _core_scalar(value: Any, dp_type: str, reason: str) -> str | int | bool:
    if dp_type in {"string", "hex", "base64"}:
        if not isinstance(value, str):
            raise ConversionError(reason)
        return value
    if dp_type in {"integer", "bitfield"}:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConversionError(reason)
        return value
    if dp_type == "boolean":
        if not isinstance(value, bool):
            raise ConversionError(reason)
        return value
    raise ConversionError(reason)


def _core_boolean_values(
    dp: dict[str, Any],
    *,
    reason: str,
    writable: bool,
) -> tuple[str | int | bool, str | int | bool]:
    _check_common_dp_semantics(dp, writable=writable)
    dp_type = _dp_type(dp)
    rules = _mapping_rules(dp)
    if not rules:
        if dp_type != "boolean":
            raise ConversionError(f"{reason}_type")
        return True, False

    raw_true = None
    raw_false = None
    true_seen = False
    false_seen = False
    raw_seen: list[str | int | bool] = []
    for rule in rules:
        if set(rule) - {"dps_val", "value", "hidden"}:
            raise ConversionError(f"{reason}_mapping")
        if "dps_val" not in rule or "value" not in rule:
            raise ConversionError(f"{reason}_mapping")
        if writable and rule.get("hidden") is True:
            continue
        friendly = rule["value"]
        if not isinstance(friendly, bool):
            raise ConversionError(f"{reason}_mapping")
        raw = _core_scalar(rule["dps_val"], dp_type, f"{reason}_mapping")
        if any(raw == previous for previous in raw_seen):
            raise ConversionError(f"{reason}_duplicate")
        raw_seen.append(raw)
        if friendly:
            if true_seen:
                raise ConversionError(f"{reason}_duplicate")
            raw_true = raw
            true_seen = True
        else:
            if false_seen:
                raise ConversionError(f"{reason}_duplicate")
            raw_false = raw
            false_seen = True

    if not true_seen or not false_seen:
        raise ConversionError(f"{reason}_mapping")
    return raw_true, raw_false


def _core_string_values(
    dp: dict[str, Any],
    *,
    reason: str,
    writable: bool,
) -> dict[str, str | int | bool]:
    _check_common_dp_semantics(dp, writable=writable)
    dp_type = _dp_type(dp)
    if dp_type not in {"string", "integer", "boolean", "bitfield"}:
        raise ConversionError(f"{reason}_type")
    rules = _mapping_rules(dp)
    if not rules:
        raise ConversionError(f"{reason}_mapping")
    result: dict[str, str | int | bool] = {}
    raws: list[str | int | bool] = []
    for rule in rules:
        if set(rule) - {"dps_val", "value", "hidden"}:
            raise ConversionError(f"{reason}_mapping")
        if "dps_val" not in rule or "value" not in rule:
            raise ConversionError(f"{reason}_mapping")
        if writable and rule.get("hidden") is True:
            continue
        friendly = rule["value"]
        if not isinstance(friendly, str) or not friendly:
            raise ConversionError(f"{reason}_friendly")
        raw = _core_scalar(rule["dps_val"], dp_type, f"{reason}_mapping")
        if friendly in result or any(raw == previous for previous in raws):
            raise ConversionError(f"{reason}_duplicate")
        result[friendly] = raw
        raws.append(raw)
    if not result:
        raise ConversionError(f"{reason}_mapping")
    return result


def _preserve_core_extra(
    prefix: str,
    name: str,
    dp: dict[str, Any],
    config: dict[str, Any],
    required: set[int],
    optional: set[int],
) -> None:
    if dp.get("force") is True or dp.get("persist") is False or dp.get("sensitive") is True:
        raise ConversionError(f"{prefix}_extra_semantics:{name}")
    if dp.get("readonly") not in (None, False, True):
        raise ConversionError(f"{prefix}_extra_semantics:{name}")
    if _mapping_rules(dp):
        raise ConversionError(f"{prefix}_extra_mapping:{name}")
    if _dp_type(dp) not in {"boolean", "integer", "string", "bitfield", "hex", "base64"}:
        raise ConversionError(f"{prefix}_extra_type:{name}")
    allowed = {
        "id", "type", "name", "optional", "readonly", "hidden", "force",
        "persist", "sensitive", "unit", "class", "category", "range", "step",
    }
    if set(dp) - allowed:
        raise ConversionError(f"{prefix}_extra_semantics:{name}")
    if dp.get("hidden") is not True and name not in {"state", "available"}:
        config.setdefault("extra_state_attributes_dps", {})[name] = _dp_id(dp)
    _merge_membership(required, optional, dp)


def _convert_button(entity: dict[str, Any]) -> Converted:
    dps = _core_named_dps(entity, "button")
    button = dps.get("button")
    if button is None:
        raise ConversionError("button_missing_button")
    _check_common_dp_semantics(button, writable=True)
    dp_type = _dp_type(button)
    rules = _mapping_rules(button)
    if not rules:
        if dp_type != "boolean":
            raise ConversionError("button_press_type")
        press_value: str | int | bool = True
    else:
        candidates: list[str | int | bool] = []
        for rule in rules:
            if set(rule) - {"dps_val", "value", "hidden"}:
                raise ConversionError("button_press_mapping")
            if rule.get("hidden") is True:
                continue
            if rule.get("value") is True:
                if "dps_val" not in rule:
                    raise ConversionError("button_press_mapping")
                candidates.append(
                    _core_scalar(rule["dps_val"], dp_type, "button_press_mapping")
                )
        if len(candidates) != 1:
            raise ConversionError("button_press_mapping")
        press_value = candidates[0]

    config: dict[str, Any] = {
        "id": _dp_id(button),
        "platform": "button",
        "button_press_value": press_value,
    }
    _entity_metadata(entity, config)
    required: set[int] = set()
    optional: set[int] = set()
    _merge_membership(required, optional, button)
    for name, dp in dps.items():
        if name == "button":
            continue
        _preserve_core_extra("button", name, dp, config, required, optional)
    return {"platform": "button", "config": config}, required, optional


def _convert_text(entity: dict[str, Any]) -> Converted:
    dps = entity.get("dps")
    if not isinstance(dps, list) or len(dps) != 1 or not isinstance(dps[0], dict):
        raise ConversionError("text_requires_single_value_dp")
    dp = dps[0]
    if dp.get("name") != "value":
        raise ConversionError("text_missing_value")
    if dp.get("force") is True or dp.get("persist") is False or dp.get("sensitive") is True:
        raise ConversionError("text_sensitive_semantics")
    if dp.get("readonly") is True:
        raise ConversionError("text_readonly")
    if dp.get("readonly") not in (None, False):
        raise ConversionError("text_semantics")
    allowed = {
        "id", "type", "name", "optional", "readonly", "hidden", "force",
        "persist", "sensitive", "range",
    }
    if set(dp) - allowed:
        raise ConversionError("text_semantics")
    if _mapping_rules(dp):
        raise ConversionError("text_mapping")
    raw_type = _dp_type(dp)
    if raw_type not in {"string", "hex", "base64"}:
        raise ConversionError("text_type")

    config: dict[str, Any] = {
        "id": _dp_id(dp),
        "platform": "text",
        "text_mode": "password" if dp.get("hidden") is True else "text",
    }
    raw_range = dp.get("range")
    if raw_range is not None:
        if not isinstance(raw_range, dict) or "min" not in raw_range or "max" not in raw_range:
            raise ConversionError("text_range")
        minimum = _range_value(raw_range["min"], 1.0, "text_range")
        maximum = _range_value(raw_range["max"], 1.0, "text_range")
        if not minimum.is_integer() or not maximum.is_integer() or minimum < 0 or maximum < minimum:
            raise ConversionError("text_range")
        config["text_min"] = int(minimum)
        config["text_max"] = int(maximum)
    if raw_type == "hex":
        config["text_pattern"] = "[0-9a-fA-F]*"
    elif raw_type == "base64":
        config["text_pattern"] = "^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$"

    _entity_metadata(entity, config)
    required, optional = _dp_membership(dp)
    return {"platform": "text", "config": config}, required, optional


def _core_position_semantics(dp: dict[str, Any], *, reason: str, writable: bool) -> tuple[float, float, bool]:
    _check_common_dp_semantics(dp, writable=writable)
    if _dp_type(dp) != "integer":
        raise ConversionError(f"{reason}_type")
    rules = _mapping_rules(dp)
    inverted = False
    if rules:
        if len(rules) != 1 or "dps_val" in rules[0]:
            raise ConversionError(f"{reason}_mapping")
        rule = rules[0]
        if set(rule) - {"invert"}:
            raise ConversionError(f"{reason}_mapping")
        inverted = rule.get("invert", False)
        if not isinstance(inverted, bool):
            raise ConversionError(f"{reason}_mapping")
    step = dp.get("step", 1)
    if isinstance(step, bool) or not isinstance(step, (int, float)) or float(step) != 1.0:
        raise ConversionError(f"{reason}_step")
    raw_range = dp.get("range", {"min": 0, "max": 100})
    if not isinstance(raw_range, dict) or "min" not in raw_range or "max" not in raw_range:
        raise ConversionError(f"{reason}_range")
    minimum = _range_value(raw_range["min"], 1.0, f"{reason}_range")
    maximum = _range_value(raw_range["max"], 1.0, f"{reason}_range")
    if maximum <= minimum:
        raise ConversionError(f"{reason}_range")
    return minimum, maximum, inverted


def _convert_valve(entity: dict[str, Any]) -> Converted:
    dps = _core_named_dps(entity, "valve")
    valve = dps.get("valve")
    if valve is None:
        raise ConversionError("valve_missing_valve")
    config: dict[str, Any] = {"id": _dp_id(valve), "platform": "valve"}
    _entity_metadata(entity, config)
    required: set[int] = set()
    optional: set[int] = set()

    if _dp_type(valve) == "integer":
        minimum, maximum, inverted = _core_position_semantics(
            valve, reason="valve_position", writable=True
        )
        config.update({
            "valve_position_control": True,
            "valve_position_min": minimum,
            "valve_position_max": maximum,
            "valve_position_inverted": inverted,
        })
    else:
        raw_open, raw_closed = _core_boolean_values(
            valve, reason="valve_state", writable=True
        )
        config["valve_open_value"] = raw_open
        config["valve_closed_value"] = raw_closed
    _merge_membership(required, optional, valve)

    switch = dps.get("switch")
    if switch is not None:
        raw_on, raw_off = _core_boolean_values(
            switch, reason="valve_switch", writable=True
        )
        config["valve_switch_dp"] = _dp_id(switch)
        config["valve_switch_on"] = raw_on
        config["valve_switch_off"] = raw_off
        _merge_membership(required, optional, switch)

    current = dps.get("current_position")
    if current is not None:
        if not config.get("valve_position_control"):
            raise ConversionError("valve_current_position_without_position_control")
        cur_min, cur_max, cur_inverted = _core_position_semantics(
            current, reason="valve_current_position", writable=False
        )
        if (
            cur_min != config["valve_position_min"]
            or cur_max != config["valve_position_max"]
            or cur_inverted != config["valve_position_inverted"]
        ):
            raise ConversionError("valve_current_position_semantics")
        config["valve_current_position_dp"] = _dp_id(current)
        _merge_membership(required, optional, current)

    for name, dp in dps.items():
        if name in {"valve", "switch", "current_position"}:
            continue
        _preserve_core_extra("valve", name, dp, config, required, optional)
    return {"platform": "valve", "config": config}, required, optional


LOCK_SPECIAL_DPS = {
    "unlock_fingerprint", "unlock_password", "unlock_temp_pwd", "unlock_dynamic_pwd",
    "unlock_offline_pwd", "unlock_card", "unlock_app", "unlock_key", "unlock_ble",
    "unlock_voice", "unlock_face", "unlock_multi", "unlock_ibeacon", "request_unlock",
    "approve_unlock", "code_unlock", "set_unlock_code", "request_intercom",
    "approve_intercom",
}


def _convert_lock(entity: dict[str, Any]) -> Converted:
    dps = _core_named_dps(entity, "lock")
    lock = dps.get("lock")
    if lock is None:
        raise ConversionError("lock_direct_control_required")
    raw_locked, raw_unlocked = _core_boolean_values(
        lock, reason="lock_control", writable=True
    )
    config: dict[str, Any] = {
        "id": _dp_id(lock),
        "platform": "lock",
        "lock_command_values": {"lock": raw_locked, "unlock": raw_unlocked},
        "lock_state_values": {"locked": raw_locked, "unlocked": raw_unlocked},
    }
    _entity_metadata(entity, config)
    required: set[int] = set()
    optional: set[int] = set()
    _merge_membership(required, optional, lock)

    state = dps.get("lock_state")
    if state is not None:
        state_locked, state_unlocked = _core_boolean_values(
            state, reason="lock_state", writable=False
        )
        config["lock_state_dp"] = _dp_id(state)
        config["lock_state_values"] = {
            "locked": state_locked,
            "unlocked": state_unlocked,
        }
        _merge_membership(required, optional, state)

    open_dp = dps.get("open")
    if open_dp is not None:
        writable_open = open_dp.get("readonly") is not True
        raw_open, raw_closed = _core_boolean_values(
            open_dp, reason="lock_open", writable=writable_open
        )
        config["lock_open_dp"] = _dp_id(open_dp)
        config["lock_open_values"] = {"open": raw_open, "closed": raw_closed}
        config["lock_open_writable"] = writable_open
        _merge_membership(required, optional, open_dp)

    jammed = dps.get("jammed")
    if jammed is not None:
        raw_jammed, raw_clear = _core_boolean_values(
            jammed, reason="lock_jammed", writable=False
        )
        config["lock_jammed_dp"] = _dp_id(jammed)
        config["lock_jammed_values"] = {"jammed": raw_jammed, "clear": raw_clear}
        _merge_membership(required, optional, jammed)

    for name, dp in dps.items():
        if name in {"lock", "lock_state", "open", "jammed"}:
            continue
        if name in LOCK_SPECIAL_DPS:
            raise ConversionError(f"lock_unsupported_dp:{name}")
        _preserve_core_extra("lock", name, dp, config, required, optional)
    return {"platform": "lock", "config": config}, required, optional


def _convert_humidifier(entity: dict[str, Any]) -> Converted:
    dps = _core_named_dps(entity, "humidifier")
    functional = {"switch", "current_humidity", "humidity", "mode", "action"}
    primary = next((dps[name] for name in ("switch", "humidity", "current_humidity", "mode", "action") if name in dps), None)
    if primary is None:
        raise ConversionError("humidifier_missing_functional_dp")

    config: dict[str, Any] = {"id": _dp_id(primary), "platform": "humidifier"}
    _entity_metadata(entity, config)
    required: set[int] = set()
    optional: set[int] = set()
    humidity_scalings: list[float] = []

    switch = dps.get("switch")
    if switch is not None:
        raw_on, raw_off = _core_boolean_values(
            switch, reason="humidifier_switch", writable=True
        )
        config["id"] = _dp_id(switch)
        config["humidifier_switch_dp"] = _dp_id(switch)
        config["humidifier_switch_on"] = raw_on
        config["humidifier_switch_off"] = raw_off
        _merge_membership(required, optional, switch)

    current = dps.get("current_humidity")
    if current is not None:
        _check_common_dp_semantics(current, writable=False)
        if _dp_type(current) != "integer":
            raise ConversionError("humidifier_current_humidity_type")
        scaling = _default_scale_rule(current)
        humidity_scalings.append(scaling)
        config["humidifier_current_humidity_dp"] = _dp_id(current)
        _merge_membership(required, optional, current)

    target = dps.get("humidity")
    if target is not None:
        _check_common_dp_semantics(target, writable=True)
        if _dp_type(target) != "integer":
            raise ConversionError("humidifier_humidity_type")
        scaling, rule = _numeric_rule(target)
        humidity_scalings.append(scaling)
        config["humidifier_target_humidity_dp"] = _dp_id(target)
        raw_range = rule.get("range", target.get("range"))
        if raw_range is not None:
            if not isinstance(raw_range, dict) or "min" not in raw_range or "max" not in raw_range:
                raise ConversionError("humidifier_humidity_range")
            minimum = _range_value(raw_range["min"], scaling, "humidifier_humidity_range")
            maximum = _range_value(raw_range["max"], scaling, "humidifier_humidity_range")
            if maximum < minimum:
                raise ConversionError("humidifier_humidity_range")
            config["humidifier_humidity_min"] = minimum
            config["humidifier_humidity_max"] = maximum
        raw_step = rule.get("step", target.get("step", 1))
        step = _range_value(raw_step, scaling, "humidifier_humidity_step")
        if step <= 0:
            raise ConversionError("humidifier_humidity_step")
        config["humidifier_humidity_step"] = step
        _merge_membership(required, optional, target)

    if humidity_scalings:
        first = humidity_scalings[0]
        if any(abs(value - first) > 1e-12 for value in humidity_scalings[1:]):
            raise ConversionError("humidifier_humidity_scaling_mismatch")
        if first != 1.0:
            config["humidifier_humidity_scaling"] = first

    mode = dps.get("mode")
    if mode is not None:
        config["humidifier_mode_dp"] = _dp_id(mode)
        config["humidifier_mode_values"] = _core_string_values(
            mode, reason="humidifier_mode", writable=True
        )
        _merge_membership(required, optional, mode)

    action = dps.get("action")
    if action is not None:
        config["humidifier_action_dp"] = _dp_id(action)
        config["humidifier_action_values"] = _core_string_values(
            action, reason="humidifier_action", writable=False
        )
        _merge_membership(required, optional, action)

    for name, dp in dps.items():
        if name in functional:
            continue
        _preserve_core_extra("humidifier", name, dp, config, required, optional)
    return {"platform": "humidifier", "config": config}, required, optional


_CONVERTERS: dict[str, Converter] = {
    "binary_sensor": _convert_binary_sensor,
    "button": _convert_button,
    "climate": _convert_climate,
    "cover": _convert_cover,
    "fan": _convert_fan,
    "humidifier": _convert_humidifier,
    "light": _convert_light,
    "lock": _convert_lock,
    "number": _convert_number,
    "select": _convert_select,
    "sensor": _convert_sensor,
    "switch": _convert_switch,
    "text": _convert_text,
    "vacuum": _convert_vacuum,
    "valve": _convert_valve,
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
        if platform in CORE_PLATFORM_NAMES:
            primary_key = (platform, int(converted["config"]["id"]))
            if any(
                existing["platform"] == primary_key[0]
                and int(existing["config"]["id"]) == primary_key[1]
                for existing in converted_entities
            ):
                raise ConversionError(f"{platform}_duplicate_primary_dp")
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
