"""Extra lossless converters enabled for productless Catalog V3 imports.

The product-ID importer intentionally stays conservative and stable. Productless
fingerprints can opt into runtime capabilities added after that importer was
written, but only through explicit converters in this module.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Callable

import import_tuya_local as base
from sensor_mapping import validate_sensor_value_mapping
from fan_mapping import (
    coerce_fan_raw,
    validate_fan_oscillation_mapping,
    validate_fan_speed_mapping,
)


ConversionError = base.ConversionError
SOURCE_LICENSE = base.SOURCE_LICENSE
SOURCE_REPOSITORY = base.SOURCE_REPOSITORY
_devices_dir = base._devices_dir
_product_ids = base._product_ids
_platforms = base._platforms


# Batch F translates only semantics that LocalTuya 6.4's declarative mapping
# engine reproduces exactly. Tuya Local features with different runtime
# behaviour stay fail-closed instead of being approximated.
_ADVANCED_SOURCE_KEYS = {"conditions", "constraint", "invalid", "value_redirect"}
_UNSUPPORTED_ADVANCED_KEYS = {"available", "mapping", "value_mirror"}
_RUNTIME_RULE_BASE_KEYS = {"dps_val", "value", "hidden", "invalid"}
_RUNTIME_CONDITION_KEYS = {"dps_val", "value", "hidden", "invalid", "value_redirect", "range", "step"}
_BASE_PROJECTION_DROP = {"conditions", "constraint", "invalid", "value_redirect"}
_SIMPLE_PRIMARY_NAMES = {
    "binary_sensor": "sensor",
    "number": "value",
    "select": "option",
    "sensor": "sensor",
    "switch": "switch",
}
_CLIMATE_SEMANTIC_NAMES = {
    "hvac_mode", "temperature", "current_temperature",
    "target_temp_low", "target_temp_high", "humidity",
    "current_humidity", "preset_mode", "fan_mode", "swing_mode",
    "swing_horizontal_mode", "hvac_action", "temperature_unit",
    "min_temperature", "max_temperature", "state", "available",
}


def _named_dps(entity: dict[str, Any], prefix: str) -> dict[str, dict[str, Any]]:
    dps = entity.get("dps")
    if not isinstance(dps, list) or not dps:
        raise ConversionError(f"{prefix}_missing_dps")
    result: dict[str, dict[str, Any]] = {}
    seen_ids: set[int] = set()
    for dp in dps:
        if not isinstance(dp, dict):
            raise ConversionError("invalid_dp")
        name = dp.get("name")
        if not isinstance(name, str) or not name:
            raise ConversionError(f"{prefix}_missing_dp_name")
        if name in result:
            raise ConversionError(f"{prefix}_duplicate_dp:{name}")
        dp_id = base._dp_id(dp)
        # Two semantic attributes pointing at the same raw DP can be meaningful
        # in Tuya Local, but LocalTuya's catalog entity identity and raw-extra
        # representation cannot reproduce that generically. Keep it fail-closed.
        if dp_id in seen_ids:
            raise ConversionError(f"{prefix}_duplicate_dp_id")
        seen_ids.add(dp_id)
        result[name] = dp
    return result


def _raw_mapping(dp: dict[str, Any]) -> list[dict[str, Any]]:
    mapping = dp.get("mapping")
    if mapping is None:
        return []
    if not isinstance(mapping, list):
        raise ConversionError("invalid_mapping")
    result = []
    for rule in mapping:
        if not isinstance(rule, dict):
            raise ConversionError("invalid_mapping_rule")
        result.append(rule)
    return result


def _runtime_scalar(value: Any, reason: str) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    raise ConversionError(reason)


def _condition_dps_value(value: Any) -> Any:
    if isinstance(value, list):
        if not value or len(value) > 32:
            raise ConversionError("advanced_mapping_condition_value")
        return [_runtime_scalar(item, "advanced_mapping_condition_value") for item in value]
    return _runtime_scalar(value, "advanced_mapping_condition_value")


def _dependency_dp(
    name: Any,
    by_name: dict[str, dict[str, Any]],
    *,
    reason: str,
) -> tuple[int, dict[str, Any]]:
    if not isinstance(name, str) or not name:
        raise ConversionError(reason)
    dp = by_name.get(name)
    if dp is None:
        raise ConversionError(f"{reason}:{name}")
    return base._dp_id(dp), dp


def _validate_constraint_dp(dp: dict[str, Any]) -> None:
    # Tuya Local decodes hex/base64 constraints and gives bitfields special
    # subset matching. LocalTuya's current advanced matcher compares cached raw
    # scalar values, so those shapes are deliberately not imported yet.
    if base._dp_type(dp) not in {"boolean", "integer", "string"}:
        raise ConversionError("advanced_mapping_constraint_type")
    if dp.get("force") is True or dp.get("persist") is False or dp.get("sensitive") is True:
        raise ConversionError("advanced_mapping_constraint_semantics")


def _validate_redirect_target(dp: dict[str, Any], *, writable_source: bool) -> None:
    if dp.get("force") is True or dp.get("persist") is False or dp.get("sensitive") is True:
        raise ConversionError("advanced_mapping_redirect_semantics")
    if set(dp) & {"mask", "mask_signed", "format", "endianness"}:
        raise ConversionError("advanced_mapping_redirect_encoding")
    # Reads recurse through LocalTuya mappings, but writes intentionally redirect
    # to the target raw DP in one step. Tuya Local recursively applies the target
    # DP's write mapping, so a writable redirect is lossless only when the target
    # itself has no mapping transformation.
    if writable_source and _raw_mapping(dp):
        raise ConversionError("advanced_mapping_redirect_target_mapping")


def _translate_advanced_mapping(
    dp: dict[str, Any],
    by_name: dict[str, dict[str, Any]],
    platform: str,
) -> tuple[list[dict[str, Any]], set[str]]:
    rules = _raw_mapping(dp)
    if not rules:
        return [], set()
    if base._dp_type(dp) == "bitfield":
        # Tuya Local uses bit containment for bitfield dps_val matching while the
        # current LocalTuya mapping engine uses scalar equality.
        raise ConversionError("advanced_mapping_bitfield")

    translated: list[dict[str, Any]] = []
    references: set[str] = set()
    writable_source = dp.get("readonly") is not True
    transform_keys = {"scale", "invert", "step", "range", "target_range"}

    for source in rules:
        unsupported = set(source) & _UNSUPPORTED_ADVANCED_KEYS
        if unsupported:
            raise ConversionError(
                "advanced_mapping_unsupported:" + ",".join(sorted(unsupported))
            )
        if source.get("default") is True:
            # Tuya Local's `default` participates in entity default selection;
            # LocalTuya validates the key but does not implement that selection.
            raise ConversionError("advanced_mapping_default")

        allowed_source = _RUNTIME_RULE_BASE_KEYS | {
            "conditions", "constraint", "value_redirect",
            # These simple transforms remain in the base projection. They are
            # intentionally not duplicated into the advanced rule.
            "scale", "invert", "step", "range", "target_range", "default",
        }
        if set(source) - allowed_source:
            raise ConversionError("advanced_mapping_rule_semantics")
        # Static mapping transforms remain in the mature base converter.  Do not
        # duplicate them into advanced_mapping_by_dp or values would be transformed
        # twice.  Batch M only overlays condition-dependent metadata below.
        # Invert/target_range are still rejected when mixed with advanced semantics
        # because their exact transform range differs from the active metadata range.
        if set(source) & {"invert", "target_range"}:
            raise ConversionError("advanced_mapping_rule_transform_semantics")

        rule: dict[str, Any] = {}
        for key in ("dps_val", "value"):
            if key in source:
                rule[key] = _runtime_scalar(source[key], "advanced_mapping_scalar")
        for key in ("hidden", "invalid"):
            if key in source:
                if not isinstance(source[key], bool):
                    raise ConversionError("advanced_mapping_boolean")
                rule[key] = source[key]

        redirect = source.get("value_redirect")
        if redirect is not None:
            redirect_id, redirect_dp = _dependency_dp(
                redirect, by_name, reason="advanced_mapping_redirect_missing"
            )
            _validate_redirect_target(redirect_dp, writable_source=writable_source)
            references.add(redirect)
            rule["value_redirect_dp"] = redirect_id

        conditions = source.get("conditions")
        constraint = source.get("constraint")
        if conditions is not None:
            if not isinstance(conditions, list) or not conditions or len(conditions) > 16:
                raise ConversionError("advanced_mapping_conditions")
            # LocalTuya can observe same-DP constraints, but on reverse mapping it
            # would also write that constraint DP. Tuya Local suppresses that side
            # effect when constraint==self, so require an explicit external DP.
            if not isinstance(constraint, str) or not constraint or constraint == dp.get("name"):
                raise ConversionError("advanced_mapping_external_constraint_required")
            constraint_id, constraint_dp = _dependency_dp(
                constraint, by_name, reason="advanced_mapping_constraint_missing"
            )
            _validate_constraint_dp(constraint_dp)
            references.add(constraint)
            rule["constraint_dp"] = constraint_id
            translated_conditions: list[dict[str, Any]] = []
            for condition in conditions:
                if not isinstance(condition, dict):
                    raise ConversionError("advanced_mapping_condition")
                unsupported_condition = set(condition) & _UNSUPPORTED_ADVANCED_KEYS
                if unsupported_condition:
                    raise ConversionError(
                        "advanced_mapping_condition_unsupported:"
                        + ",".join(sorted(unsupported_condition))
                    )
                if set(condition) - _RUNTIME_CONDITION_KEYS:
                    raise ConversionError("advanced_mapping_condition_semantics")
                dynamic_metadata = set(condition) & {"range", "step"}
                if dynamic_metadata and platform not in {"climate", "number"}:
                    raise ConversionError("advanced_mapping_condition_semantics")
                if "dps_val" not in condition:
                    raise ConversionError("advanced_mapping_condition_missing_dps_val")
                out: dict[str, Any] = {
                    "dps_val": _condition_dps_value(condition["dps_val"])
                }
                for key in ("value",):
                    if key in condition:
                        out[key] = _runtime_scalar(
                            condition[key], "advanced_mapping_condition_scalar"
                        )
                for key in ("hidden", "invalid"):
                    if key in condition:
                        if not isinstance(condition[key], bool):
                            raise ConversionError("advanced_mapping_condition_boolean")
                        out[key] = condition[key]
                if "range" in condition:
                    value_range = condition["range"]
                    if (
                        not isinstance(value_range, dict)
                        or set(value_range) != {"min", "max"}
                        or any(isinstance(value_range[k], bool) or not isinstance(value_range[k], (int, float)) for k in ("min", "max"))
                        or value_range["max"] < value_range["min"]
                    ):
                        raise ConversionError("advanced_mapping_condition_range")
                    out["range"] = {"min": value_range["min"], "max": value_range["max"]}
                if "step" in condition:
                    step = condition["step"]
                    if isinstance(step, bool) or not isinstance(step, (int, float)) or step <= 0:
                        raise ConversionError("advanced_mapping_condition_step")
                    out["step"] = step
                condition_redirect = condition.get("value_redirect")
                if condition_redirect is not None:
                    redirect_id, redirect_dp = _dependency_dp(
                        condition_redirect,
                        by_name,
                        reason="advanced_mapping_redirect_missing",
                    )
                    _validate_redirect_target(
                        redirect_dp, writable_source=writable_source
                    )
                    references.add(condition_redirect)
                    out["value_redirect_dp"] = redirect_id
                translated_conditions.append(out)
            rule["conditions"] = translated_conditions
        elif constraint is not None:
            raise ConversionError("advanced_mapping_constraint_without_conditions")

        if not rule:
            raise ConversionError("advanced_mapping_empty_rule")
        translated.append(rule)

    if not translated:
        return [], set()
    return translated, references


def _project_mapping_for_base(
    dp: dict[str, Any], platform: str, name: str
) -> dict[str, Any]:
    """Project mappings only when a base converter needs a finite HA enum domain."""
    enum_names = {
        "climate": {
            "hvac_mode", "preset_mode", "fan_mode", "swing_mode",
            "swing_horizontal_mode", "hvac_action", "temperature_unit",
        },
        "water_heater": {"operation_mode", "temperature_unit"},
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
            # Tuya Local exposes the mapping's own value first, then any visible
            # condition-specific values.  Invalid-only conditions therefore must
            # not erase an otherwise valid base enum value.
            if "value" in source:
                add_output(source["value"])
            for condition in conditions:
                if not isinstance(condition, dict):
                    raise ConversionError("advanced_mapping_condition")
                if condition.get("invalid") is True or condition.get("hidden") is True:
                    continue
                if "value" in condition:
                    add_output(condition["value"])
                elif "value" in source:
                    add_output(source["value"])
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
    if platform == "water_heater" and name == "operation_mode":
        projected["_productless_source_type"] = base._dp_type(dp)
    return projected


def _validate_consumed_dependency(dp: dict[str, Any]) -> None:
    if dp.get("force") is True or dp.get("persist") is False or dp.get("sensitive") is True:
        raise ConversionError("advanced_mapping_dependency_semantics")
    if set(dp) & {"mask", "mask_signed", "format", "endianness"}:
        raise ConversionError("advanced_mapping_dependency_encoding")



def _normalize_climate_temperature_unit(entity: dict[str, Any]) -> dict[str, Any]:
    """Normalize explicit Tuya Local C/F friendly values for LocalTuya Climate.

    Tuya Local device YAML commonly exposes friendly ``C``/``F`` while the
    LocalTuya runtime's catalog contract uses ``celsius``/``fahrenheit``. Raw
    device values remain untouched. Forward/default rules without an exact raw
    value are deliberately left fail-closed because they cannot define a
    reversible raw unit map.
    """
    if entity.get("entity") != "climate":
        return entity
    dps = entity.get("dps")
    if not isinstance(dps, list):
        return entity
    unit = next(
        (
            dp for dp in dps
            if isinstance(dp, dict) and dp.get("name") == "temperature_unit"
        ),
        None,
    )
    if unit is None:
        return entity
    rules = _raw_mapping(unit)
    if not rules:
        return entity

    normalized = copy.deepcopy(entity)
    normalized_unit = next(
        dp for dp in normalized["dps"]
        if isinstance(dp, dict) and dp.get("name") == "temperature_unit"
    )
    normalized_rules = _raw_mapping(normalized_unit)
    seen_units: set[str] = set()
    seen_raw: list[Any] = []
    aliases = {
        "C": "celsius",
        "°C": "celsius",
        "celsius": "celsius",
        "F": "fahrenheit",
        "°F": "fahrenheit",
        "fahrenheit": "fahrenheit",
    }
    for rule in normalized_rules:
        if set(rule) - {"dps_val", "value", "hidden"}:
            raise ConversionError("climate_temperature_unit_mapping")
        if rule.get("hidden") is True or "dps_val" not in rule or "value" not in rule:
            raise ConversionError("climate_temperature_unit_mapping")
        friendly = rule["value"]
        if not isinstance(friendly, str) or friendly not in aliases:
            raise ConversionError("climate_temperature_unit_friendly")
        friendly = aliases[friendly]
        raw = rule["dps_val"]
        if friendly in seen_units or any(raw == previous and type(raw) is type(previous) for previous in seen_raw):
            raise ConversionError("climate_temperature_unit_duplicate")
        seen_units.add(friendly)
        seen_raw.append(raw)
        rule["value"] = friendly
    if seen_units != {"celsius", "fahrenheit"}:
        raise ConversionError("climate_temperature_unit_mapping")
    return normalized


def _prepare_climate_limit_precisions(
    entity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, float]]:
    """Project simple scaled Climate limit DPS onto LocalTuya precision config.

    Tuya Local applies ``scale`` on read for min/max temperature registers.
    LocalTuya keeps those registers as raw DPS and applies an independent
    precision multiplier. Only one transform-only ``scale`` rule is accepted;
    all richer mapping semantics stay fail-closed in the base converter.
    """
    transformed = copy.deepcopy(entity)
    precisions: dict[str, float] = {}
    for dp in transformed.get("dps", []):
        if not isinstance(dp, dict) or dp.get("name") not in {"min_temperature", "max_temperature"}:
            continue
        rules = _raw_mapping(dp)
        if not rules:
            continue
        if len(rules) != 1 or set(rules[0]) != {"scale"}:
            continue
        scale = rules[0].get("scale")
        if isinstance(scale, bool) or not isinstance(scale, (int, float)):
            continue
        scale = float(scale)
        if not math.isfinite(scale) or scale <= 0:
            continue
        key = (
            "min_temperature_precision"
            if dp.get("name") == "min_temperature"
            else "max_temperature_precision"
        )
        precisions[key] = 1.0 / scale
        dp.pop("mapping", None)
    return transformed, precisions


def _prepare_climate_dynamic_target_range(
    entity: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Bootstrap the mature Climate converter for condition-only target ranges.

    Tuya Local can make the writable target-temperature range depend on another
    DP through mapping conditions. LocalTuya's advanced runtime reproduces that
    metadata exactly, but the mature converter requires one range while building
    its static config. Inject a conversion-only union range, then discard the
    resulting static min/max constants after conversion so runtime metadata stays
    authoritative. When no condition is active, LocalTuya falls back to HA's
    defaults, matching Tuya Local's ``range() is None`` behaviour.
    """
    transformed = copy.deepcopy(entity)
    dps = transformed.get("dps")
    if not isinstance(dps, list):
        return entity, False

    target = next(
        (
            dp for dp in dps
            if isinstance(dp, dict) and dp.get("name") == "temperature"
        ),
        None,
    )
    if target is None or target.get("range") is not None:
        return entity, False

    rules = _raw_mapping(target)
    if not rules:
        return entity, False

    ranges: list[tuple[float, float]] = []
    saw_conditional_range = False
    for rule in rules:
        # A real static rule range already gives the mature converter an exact
        # fallback, so do not replace it with a synthetic bootstrap range.
        if "range" in rule:
            return entity, False
        conditions = rule.get("conditions")
        if not isinstance(conditions, list):
            continue
        for condition in conditions:
            if not isinstance(condition, dict) or "range" not in condition:
                continue
            saw_conditional_range = True
            value_range = condition.get("range")
            if not isinstance(value_range, dict) or set(value_range) != {"min", "max"}:
                continue
            minimum = value_range.get("min")
            maximum = value_range.get("max")
            if (
                isinstance(minimum, bool)
                or isinstance(maximum, bool)
                or not isinstance(minimum, (int, float))
                or not isinstance(maximum, (int, float))
                or maximum < minimum
            ):
                continue
            ranges.append((float(minimum), float(maximum)))

    # Malformed conditional metadata is intentionally not hidden here. Without
    # a bootstrap range the advanced translator will emit its precise fail-closed
    # validation error before the base converter is called.
    if not saw_conditional_range or not ranges:
        return entity, False

    minimum = min(item[0] for item in ranges)
    maximum = max(item[1] for item in ranges)
    if minimum.is_integer():
        minimum = int(minimum)
    if maximum.is_integer():
        maximum = int(maximum)
    target["range"] = {"min": minimum, "max": maximum}
    return transformed, True


def _prepare_advanced_entity(
    entity: dict[str, Any], platform: str
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], set[int]]:
    raw_dps = entity.get("dps")
    if not isinstance(raw_dps, list) or not raw_dps:
        return entity, {}, set()
    def needs_advanced(name: Any, rule: dict[str, Any]) -> bool:
        if set(rule) & (_ADVANCED_SOURCE_KEYS | _UNSUPPORTED_ADVANCED_KEYS):
            return True
        # Tuya Local hidden mappings still participate in forward/read mapping
        # but are excluded from value lists and reverse writes. LocalTuya's
        # advanced mapper has the same semantics. Batch N enables this only for
        # Climate swing enums where hidden rules are forward-only fallbacks.
        return (
            platform == "climate"
            and name in {"swing_mode", "swing_horizontal_mode"}
            and rule.get("hidden") is True
        )

    def dp_needs_advanced(name: Any, rules: list[dict[str, Any]]) -> bool:
        if any(needs_advanced(name, rule) for rule in rules):
            return True
        if platform != "climate" or name != "hvac_action" or len(rules) < 2:
            return False
        # Read-only HVAC action can legitimately be many-to-one (several raw
        # device states collapse to heating/idle). The mature converter stores
        # friendly->raw and therefore cannot represent that losslessly. Route
        # only fully explicit, non-null static mappings through the per-DP
        # advanced mapper, while keeping null/default fallbacks fail-closed.
        values: list[Any] = []
        for rule in rules:
            if set(rule) - {"dps_val", "value"}:
                return False
            if "dps_val" not in rule or rule.get("dps_val") is None or "value" not in rule:
                return False
            value = rule.get("value")
            if not isinstance(value, str) or not value:
                return False
            values.append(value)
        return len(set(values)) < len(values)

    has_advanced = False
    for raw_dp in raw_dps:
        if not isinstance(raw_dp, dict):
            continue
        name = raw_dp.get("name")
        if dp_needs_advanced(name, _raw_mapping(raw_dp)):
            has_advanced = True
            break
    if not has_advanced:
        return entity, {}, set()

    by_name = _named_dps(entity, platform)
    advanced_by_dp: dict[str, list[dict[str, Any]]] = {}
    referenced_names: set[str] = set()
    transformed = copy.deepcopy(entity)
    transformed_by_name = _named_dps(transformed, platform)

    for name, original_dp in by_name.items():
        rules = _raw_mapping(original_dp)
        if not dp_needs_advanced(name, rules):
            continue
        translated, references = _translate_advanced_mapping(original_dp, by_name, platform)
        if translated:
            advanced_by_dp[str(base._dp_id(original_dp))] = translated
            referenced_names.update(references)
            transformed_by_name[name].clear()
            transformed_by_name[name].update(_project_mapping_for_base(original_dp, platform, name))

    if not advanced_by_dp:
        return entity, {}, set()

    membership_ids = {int(dp_id) for dp_id in advanced_by_dp}
    for name in referenced_names:
        dependency = by_name[name]
        _validate_consumed_dependency(dependency)
        membership_ids.add(base._dp_id(dependency))

    # Complex platforms may use private redirect/constraint DPS that have no
    # independent HA-facing meaning (for example Fahrenheit shadow temperature
    # registers). Keep those DPS in fingerprint/runtime membership, but do not
    # hand them to the mature platform converter as generic extra attributes.
    # Named semantic DPS remain visible to the converter even when referenced.
    if platform == "climate" and referenced_names:
        internal_names = referenced_names - _CLIMATE_SEMANTIC_NAMES
        if internal_names:
            transformed["dps"] = [
                dp for dp in transformed.get("dps", [])
                if not (isinstance(dp, dict) and dp.get("name") in internal_names)
            ]

    # Simple LocalTuya entity converters historically require exactly one DP.
    # Batch F consumes only DPs that exist solely as declarative mapping
    # dependencies. Generic multi-DP entity support remains Batch G.
    primary_name = _SIMPLE_PRIMARY_NAMES.get(platform)
    if primary_name is not None and len(transformed.get("dps", [])) > 1:
        primary = transformed_by_name.get(primary_name)
        if primary is None:
            return transformed, advanced_by_dp, membership_ids
        extras = set(transformed_by_name) - {primary_name}
        if extras and extras.issubset(referenced_names):
            transformed["dps"] = [primary]

    return transformed, advanced_by_dp, membership_ids


def _advanced_dependency_ids(advanced_by_dp: dict[str, list[dict[str, Any]]]) -> set[int]:
    """Return DPS referenced only as advanced-mapping dependencies."""
    result: set[int] = set()
    for rules in advanced_by_dp.values():
        for rule in rules:
            for key in ("constraint_dp", "value_redirect_dp"):
                value = rule.get(key)
                if value is not None:
                    result.add(int(value))
            for condition in rule.get("conditions", []):
                if not isinstance(condition, dict):
                    continue
                value = condition.get("value_redirect_dp")
                if value is not None:
                    result.add(int(value))
    return result


def _mapped_extra_runtime_rules(
    dp: dict[str, Any], platform: str, name: str
) -> list[dict[str, Any]]:
    """Translate only extra-attribute mappings the runtime reproduces exactly."""
    rules = _raw_mapping(dp)
    if not rules:
        return []

    # Reuse the mature raw-extra validator after removing only the mapping.
    # This keeps encoded/sensitive/unsupported DP semantics fail-closed while
    # allowing the separate mapped-extra runtime channel to own value mapping.
    probe = copy.deepcopy(dp)
    probe.pop("mapping", None)
    base._preserve_core_extra(platform, name, probe, {}, set(), set())

    dp_type = base._dp_type(dp)
    if len(rules) == 1 and set(rules[0]) == {"scale"}:
        if dp_type != "integer":
            raise ConversionError(f"{platform}_mapped_extra_scale_type:{name}")
        scale = rules[0].get("scale")
        if isinstance(scale, bool) or not isinstance(scale, (int, float)):
            raise ConversionError(f"{platform}_mapped_extra_scale:{name}")
        scale = float(scale)
        if not math.isfinite(scale) or scale <= 0:
            raise ConversionError(f"{platform}_mapped_extra_scale:{name}")
        return [{"scale": scale}]

    if dp_type not in {"boolean", "integer", "string"}:
        raise ConversionError(f"{platform}_mapped_extra_type:{name}")

    translated: list[dict[str, Any]] = []
    seen_raw: list[Any] = []
    for rule in rules:
        if set(rule) != {"dps_val", "value"}:
            raise ConversionError(f"{platform}_mapped_extra_mapping:{name}")
        raw = rule.get("dps_val")
        if raw is None:
            # LocalTuya's dps() treats a cached None as unknown and deliberately
            # does not run it through advanced mapping, so null/default rules
            # cannot be represented as mapped extra attributes yet.
            raise ConversionError(f"{platform}_mapped_extra_null:{name}")
        if dp_type == "boolean" and not isinstance(raw, bool):
            raise ConversionError(f"{platform}_mapped_extra_raw_type:{name}")
        if dp_type == "integer" and (not isinstance(raw, int) or isinstance(raw, bool)):
            raise ConversionError(f"{platform}_mapped_extra_raw_type:{name}")
        if dp_type == "string" and not isinstance(raw, str):
            raise ConversionError(f"{platform}_mapped_extra_raw_type:{name}")
        if any(raw == previous and type(raw) is type(previous) for previous in seen_raw):
            raise ConversionError(f"{platform}_mapped_extra_duplicate_raw:{name}")
        seen_raw.append(raw)
        translated.append({
            "dps_val": _runtime_scalar(raw, f"{platform}_mapped_extra_scalar:{name}"),
            "value": _runtime_scalar(rule.get("value"), f"{platform}_mapped_extra_scalar:{name}"),
        })
    return translated


def _store_mapped_extra(
    platform: str,
    name: str,
    dp: dict[str, Any],
    rules: list[dict[str, Any]],
    advanced_by_dp: dict[str, list[dict[str, Any]]],
    config: dict[str, Any],
    required: set[int],
    optional: set[int],
) -> None:
    """Expose one extra attribute through dps() instead of the raw status cache."""
    dp_id = base._dp_id(dp)
    key = str(dp_id)
    existing = advanced_by_dp.get(key)
    if existing is not None and existing != rules:
        raise ConversionError(f"{platform}_mapped_extra_dp_conflict:{name}")
    advanced_by_dp[key] = copy.deepcopy(rules)

    raw_attrs = config.get("extra_state_attributes_dps", {})
    mapped_attrs = config.setdefault("mapped_extra_state_attributes_dps", {})
    if name in raw_attrs or name in mapped_attrs:
        raise ConversionError(f"{platform}_mapped_extra_name_conflict:{name}")
    if name not in {"state", "available"}:
        if len(raw_attrs) + len(mapped_attrs) >= 32:
            raise ConversionError("multi_dp_too_many_extra_attributes")
        mapped_attrs[name] = dp_id
    if not mapped_attrs:
        config.pop("mapped_extra_state_attributes_dps", None)
    base._merge_membership(required, optional, dp)


def _prepare_complex_mapped_extras(
    entity: dict[str, Any],
    platform: str,
) -> tuple[dict[str, Any], list[tuple[dict[str, Any], list[dict[str, Any]]]]]:
    """Remove safe mapped extras before complex mature converters reject them."""
    if platform != "climate":
        return entity, []
    dps = entity.get("dps")
    if not isinstance(dps, list):
        return entity, []

    transformed = copy.deepcopy(entity)
    kept: list[dict[str, Any]] = []
    mapped: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for dp in transformed.get("dps", []):
        if not isinstance(dp, dict):
            kept.append(dp)
            continue
        name = dp.get("name")
        if not isinstance(name, str) or name in _CLIMATE_SEMANTIC_NAMES or not _raw_mapping(dp):
            kept.append(dp)
            continue
        try:
            rules = _mapped_extra_runtime_rules(dp, platform, name)
        except ConversionError:
            # Leave unsupported shapes untouched so the mature converter emits
            # its normal fail-closed reason instead of silently consuming them.
            kept.append(dp)
            continue
        if not rules:
            kept.append(dp)
            continue
        mapped.append((copy.deepcopy(dp), rules))
    transformed["dps"] = kept
    return transformed, mapped


def _split_simple_multi_dp_entity(
    entity: dict[str, Any], platform: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Split a simple entity into one functional DP plus lossless raw extras.

    Tuya Local exposes unconsumed DPS as extra state attributes. LocalTuya can
    represent the same raw attributes through ``extra_state_attributes_dps``.
    Batch G therefore permits multiple DPS only for the simple platforms whose
    mature converter has exactly one functional DP.
    """
    primary_name = _SIMPLE_PRIMARY_NAMES.get(platform)
    dps = entity.get("dps")
    if primary_name is None or not isinstance(dps, list) or len(dps) <= 1:
        return entity, []

    named: dict[str, dict[str, Any]] = {}
    for dp in dps:
        if not isinstance(dp, dict):
            raise ConversionError("invalid_dp")
        name = dp.get("name")
        if not isinstance(name, str) or not name:
            raise ConversionError(f"{platform}_missing_dp_name")
        if name in named:
            raise ConversionError(f"{platform}_duplicate_dp:{name}")
        named[name] = dp

    primary = named.get(primary_name)
    if primary is None:
        raise ConversionError(f"expected_dp_name:{primary_name}")

    # Duplicate raw DP aliases are safe only when they agree on required vs
    # optional membership. The raw value may then be exposed under another
    # attribute name without requesting a contradictory fingerprint state.
    primary_id = base._dp_id(primary)
    primary_membership = base._dp_membership(primary)
    for dp in dps:
        if dp is primary:
            continue
        if base._dp_id(dp) == primary_id and base._dp_membership(dp) != primary_membership:
            raise ConversionError("multi_dp_membership_conflict")

    single = copy.deepcopy(entity)
    single["dps"] = [copy.deepcopy(primary)]
    extras = [copy.deepcopy(dp) for dp in dps if dp is not primary]
    return single, extras


def _preserve_simple_multi_dp_extras(
    platform: str,
    extras: list[dict[str, Any]],
    advanced_by_dp: dict[str, list[dict[str, Any]]],
    config: dict[str, Any],
    required: set[int],
    optional: set[int],
) -> None:
    dependency_ids = _advanced_dependency_ids(advanced_by_dp)
    advanced_source_ids = {int(dp_id) for dp_id in advanced_by_dp}

    for dp in extras:
        dp_id = base._dp_id(dp)
        name = dp.get("name")
        if not isinstance(name, str) or not name:
            raise ConversionError(f"{platform}_missing_dp_name")

        # Constraint/redirect DPS are internal to Batch F and already retained
        # in fingerprint membership. Do not expose them as unrelated raw attrs.
        if dp_id in dependency_ids:
            continue

        # An extra DP with its own advanced mapping has HA-facing semantics of
        # its own. Treating it as a raw attribute would silently discard them.
        if dp_id in advanced_source_ids:
            raise ConversionError(f"multi_dp_advanced_extra:{name}")

        if _raw_mapping(dp):
            try:
                rules = _mapped_extra_runtime_rules(dp, platform, name)
            except ConversionError as err:
                raise ConversionError(f"multi_dp_mapped_extra:{name}") from err
            _store_mapped_extra(
                platform, name, dp, rules, advanced_by_dp, config, required, optional
            )
            continue

        raw_attrs = config.get("extra_state_attributes_dps", {})
        mapped_attrs = config.get("mapped_extra_state_attributes_dps", {})
        will_expose = dp.get("hidden") is not True and name not in {"state", "available"}
        if will_expose and len(raw_attrs) + len(mapped_attrs) >= 32:
            raise ConversionError("multi_dp_too_many_extra_attributes")

        base._preserve_core_extra(
            platform, name, dp, config, required, optional
        )



def _prepare_runtime_flags(
    entity: dict[str, Any], platform: str
) -> tuple[dict[str, Any], bool, set[str], set[int]]:
    """Project Tuya Local hidden/force/persist semantics onto catalog runtime.

    ``force`` is consumed because every DP that survives conversion is already
    explicitly requested by LocalTuya. ``hidden`` on entity means disabled by
    default; hidden DPs remain in fingerprint membership but are not exposed as
    extra attributes. ``persist: false`` is carried to the runtime cache policy.
    """
    transformed = copy.deepcopy(entity)
    entity_hidden = transformed.get("hidden")
    disabled_default = False
    if entity_hidden is True:
        disabled_default = True
        transformed.pop("hidden", None)
    elif entity_hidden in (None, False):
        transformed.pop("hidden", None)
    elif entity_hidden == "unavailable":
        raise ConversionError("entity_hidden_unavailable")
    else:
        raise ConversionError("entity_hidden")

    hidden_extra_names: set[str] = set()
    non_persistent_dps: set[int] = set()
    dps = transformed.get("dps")
    if isinstance(dps, list):
        for dp in dps:
            if not isinstance(dp, dict):
                continue
            name = dp.get("name")
            if dp.get("hidden") is True:
                if isinstance(name, str) and name:
                    hidden_extra_names.add(name)
                dp.pop("hidden", None)
            elif dp.get("hidden") not in (None, False):
                raise ConversionError("dp_hidden")
            else:
                dp.pop("hidden", None)

            force = dp.get("force")
            if force is True:
                # LocalTuya requests every declared/consumed catalog DP.
                dp.pop("force", None)
            elif force not in (None, False):
                raise ConversionError("dp_force")
            else:
                dp.pop("force", None)

            if dp.get("persist") is False:
                non_persistent_dps.add(base._dp_id(dp))
                dp.pop("persist", None)
            elif dp.get("persist") in (None, True):
                dp.pop("persist", None)
            else:
                raise ConversionError("dp_persist")

    return transformed, disabled_default, hidden_extra_names, non_persistent_dps


def _apply_runtime_flags(
    converted: dict[str, Any],
    *,
    disabled_default: bool,
    hidden_extra_names: set[str],
    non_persistent_dps: set[int],
) -> None:
    config = converted["config"]
    if disabled_default:
        config["entity_registry_enabled_default"] = False

    for key in ("extra_state_attributes_dps", "mapped_extra_state_attributes_dps"):
        extras = config.get(key)
        if isinstance(extras, dict) and hidden_extra_names:
            for name in hidden_extra_names:
                extras.pop(name, None)
            if not extras:
                config.pop(key, None)

    if non_persistent_dps:
        config["non_persistent_dps"] = sorted(non_persistent_dps)


def _advanced_wrapper(
    platform: str, converter: Callable[..., base.Converted]
) -> Callable[..., base.Converted]:
    def wrapped(entity: dict[str, Any], *args, **kwargs) -> base.Converted:
        flagged, disabled_default, hidden_extra_names, non_persistent_dps = (
            _prepare_runtime_flags(entity, platform)
        )
        climate_limit_precisions: dict[str, float] = {}
        climate_dynamic_target_range = False
        if platform == "climate":
            flagged = _normalize_climate_temperature_unit(flagged)
            flagged, climate_limit_precisions = _prepare_climate_limit_precisions(flagged)
            flagged, climate_dynamic_target_range = _prepare_climate_dynamic_target_range(flagged)
        prepared, advanced_by_dp, membership_ids = _prepare_advanced_entity(
            flagged, platform
        )
        prepared, complex_mapped_extras = _prepare_complex_mapped_extras(
            prepared, platform
        )
        single, extras = _split_simple_multi_dp_entity(prepared, platform)
        converted, required, optional = converter(single, *args, **kwargs)
        if climate_limit_precisions:
            converted["config"].update(climate_limit_precisions)
        if climate_dynamic_target_range:
            # The injected union range existed only to satisfy the mature
            # converter. Runtime advanced metadata owns the actual active range.
            converted["config"].pop("min_temperature_const", None)
            converted["config"].pop("max_temperature_const", None)

        for mapped_dp, rules in complex_mapped_extras:
            name = mapped_dp.get("name")
            if not isinstance(name, str) or not name:
                raise ConversionError(f"{platform}_missing_dp_name")
            _store_mapped_extra(
                platform, name, mapped_dp, rules, advanced_by_dp,
                converted["config"], required, optional
            )

        if extras:
            _preserve_simple_multi_dp_extras(
                platform,
                extras,
                advanced_by_dp,
                converted["config"],
                required,
                optional,
            )

        _apply_runtime_flags(
            converted,
            disabled_default=disabled_default,
            hidden_extra_names=hidden_extra_names,
            non_persistent_dps=non_persistent_dps,
        )

        if not advanced_by_dp:
            return converted, required, optional

        converted["config"]["advanced_mapping_by_dp"] = advanced_by_dp
        originals = {
            base._dp_id(dp): dp
            for dp in entity.get("dps", [])
            if isinstance(dp, dict)
        }
        for dp_id in membership_ids:
            dp = originals.get(dp_id)
            if dp is None:
                raise ConversionError("advanced_mapping_dependency_missing_dp")
            base._merge_membership(required, optional, dp)
        return converted, required, optional

    return wrapped


def _simple_time_component(dp: dict[str, Any], *, reason: str) -> None:
    base._check_common_dp_semantics(dp, writable=True)
    if base._dp_type(dp) != "integer":
        raise ConversionError(f"{reason}_type")
    if base._mapping_rules(dp):
        raise ConversionError(f"{reason}_mapping")
    allowed = {
        "id", "type", "name", "optional", "readonly", "hidden", "force",
        "persist", "sensitive", "range", "step", "unit", "class", "category",
    }
    if set(dp) - allowed:
        raise ConversionError(f"{reason}_semantics")
    step = dp.get("step", 1)
    if isinstance(step, bool) or not isinstance(step, (int, float)) or float(step) != 1.0:
        raise ConversionError(f"{reason}_step")


def _convert_time(entity: dict[str, Any]) -> base.Converted:
    """Convert Tuya Local hour/minute/second time entities losslessly.

    Tuya Local folds missing higher precision into the next available component:
    no hour DP means minutes contain total minutes; no minute DP means seconds
    contain total seconds. LocalTuya Batch B implements the same algorithm.
    """
    if entity.get("class") is not None:
        raise ConversionError("time_device_class")
    base._entity_metadata(entity, {})
    dps = _named_dps(entity, "time")
    functional = {"hour", "minute", "second", "hms"}

    if "hms" in dps:
        raise ConversionError("time_hms_not_lossless")

    components = [dps[name] for name in ("hour", "minute", "second") if name in dps]
    if not components:
        raise ConversionError("time_missing_component")

    required: set[int] = set()
    optional: set[int] = set()
    config: dict[str, Any] = {"platform": "time"}

    for name in ("hour", "minute", "second"):
        dp = dps.get(name)
        if dp is None:
            continue
        _simple_time_component(dp, reason=f"time_{name}")
        config[f"time_{name}_dp"] = base._dp_id(dp)
        base._merge_membership(required, optional, dp)

    primary = next((dp for dp in components if not bool(dp.get("optional"))), components[0])
    config["id"] = base._dp_id(primary)

    for name, dp in dps.items():
        if name in functional:
            continue
        base._preserve_core_extra("time", name, dp, config, required, optional)

    return {"platform": "time", "config": config}, required, optional


def _event_scalar(value: Any, dp_type: str) -> str | int | bool:
    if dp_type == "string":
        if not isinstance(value, str):
            raise ConversionError("event_mapping")
        return value
    if dp_type in {"integer", "bitfield"}:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConversionError("event_mapping")
        return value
    if dp_type == "boolean":
        if not isinstance(value, bool):
            raise ConversionError("event_mapping")
        return value
    raise ConversionError("event_type")


def _convert_event(entity: dict[str, Any]) -> base.Converted:
    """Convert exact static Tuya event mappings."""
    dps = _named_dps(entity, "event")
    event = dps.get("event")
    if event is None:
        raise ConversionError("event_missing_event")
    base._check_common_dp_semantics(event, writable=False)
    dp_type = base._dp_type(event)
    if dp_type not in {"string", "integer", "bitfield", "boolean"}:
        raise ConversionError("event_type")

    rules = base._mapping_rules(event)
    if not rules:
        raise ConversionError("event_missing_mapping")
    values: dict[str, str | int | bool] = {}
    raw_seen: list[str | int | bool] = []
    for rule in rules:
        if set(rule) - {"dps_val", "value", "hidden", "default"}:
            raise ConversionError("event_mapping")
        if rule.get("hidden") is True or "dps_val" not in rule or "value" not in rule:
            raise ConversionError("event_mapping")
        friendly = rule["value"]
        if not isinstance(friendly, str) or not friendly.strip():
            raise ConversionError("event_mapping")
        friendly = friendly.strip()
        raw = _event_scalar(rule["dps_val"], dp_type)
        if friendly in values or any(raw == previous for previous in raw_seen):
            raise ConversionError("event_duplicate")
        values[friendly] = raw
        raw_seen.append(raw)

    config: dict[str, Any] = {
        "id": base._dp_id(event),
        "platform": "event",
        "event_dp": base._dp_id(event),
        "event_types": values,
    }
    device_class = entity.get("class")
    if device_class is not None:
        if not isinstance(device_class, str) or not device_class.strip():
            raise ConversionError("event_device_class")
        config["event_device_class"] = device_class.strip()

    metadata_probe: dict[str, Any] = {}
    base._entity_metadata({k: v for k, v in entity.items() if k != "class"}, metadata_probe)

    required: set[int] = set()
    optional: set[int] = set()
    base._merge_membership(required, optional, event)
    for name, dp in dps.items():
        if name == "event":
            continue
        base._preserve_core_extra("event", name, dp, config, required, optional)

    return {"platform": "event", "config": config}, required, optional


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


def _convert_sensor_productless(entity: dict[str, Any]) -> base.Converted:
    """Preserve ordered raw-specific read mappings without legacy rounding."""
    dp = base._single_named_dp(entity, "sensor")
    rules = _raw_mapping(dp)
    if not rules:
        return base._convert_sensor(entity)
    base._check_common_dp_semantics(dp, writable=False)
    if dp.get("precision") is not None:
        raise ConversionError("sensor_precision")
    spec = {"raw_type": base._dp_type(dp), "rules": rules}
    if "range" in dp:
        spec["range"] = dp["range"]
    normalized = validate_sensor_value_mapping(spec)
    if normalized is None:
        raise ConversionError("sensor_value_mapping_semantics")
    projected = copy.deepcopy(entity)
    projected["dps"][0].pop("mapping", None)
    converted, required, optional = base._convert_sensor(projected)
    converted["config"]["sensor_value_mapping"] = normalized
    return converted, required, optional


# Extend only the productless conversion surface. Keep the mature product-ID
# importer unchanged while wrapping its converters for Batch F on this module's
# develop-only path.
base.SUPPORTED_PLATFORMS.update({"time", "event", "water_heater"})
_original_converters = dict(base._CONVERTERS)
_original_converters["binary_sensor"] = _convert_binary_sensor_productless
_original_converters["sensor"] = _convert_sensor_productless
_original_converters["fan"] = _convert_fan_productless
_original_converters["water_heater"] = _convert_water_heater_productless
for _platform, _converter in _original_converters.items():
    base._CONVERTERS[_platform] = _advanced_wrapper(_platform, _converter)

# convert_profile has a special light-scene path that calls _convert_light
# directly rather than through _CONVERTERS, so wrap that reference as well.
if "light" in _original_converters:
    base._convert_light = _advanced_wrapper("light", base._convert_light)

base._CONVERTERS.update({
    "time": _advanced_wrapper("time", _convert_time),
    "event": _advanced_wrapper("event", _convert_event),
})


def convert_profile(*args, **kwargs):
    return base.convert_profile(*args, **kwargs)
