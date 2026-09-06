"""Extra lossless converters enabled for productless Catalog V3 imports.

The product-ID importer intentionally stays conservative and stable. Productless
fingerprints can opt into runtime capabilities added after that importer was
written, but only through explicit converters in this module.
"""

from __future__ import annotations

import copy
from typing import Any, Callable

import import_tuya_local as base


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
_RUNTIME_CONDITION_KEYS = {"dps_val", "value", "hidden", "invalid", "value_redirect"}
_BASE_PROJECTION_DROP = {"conditions", "constraint", "invalid", "value_redirect"}
_SIMPLE_PRIMARY_NAMES = {
    "binary_sensor": "sensor",
    "number": "value",
    "select": "option",
    "sensor": "sensor",
    "switch": "switch",
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

    for source in rules:
        if not (set(source) & (_ADVANCED_SOURCE_KEYS | _UNSUPPORTED_ADVANCED_KEYS)):
            continue
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
                    # Dynamic scale/range/step changes also alter HA limits and
                    # precision in Tuya Local. LocalTuya 6.4 has static entity
                    # metadata for those, so importing them would only be partial.
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


def _project_mapping_for_base(dp: dict[str, Any]) -> dict[str, Any]:
    projected = copy.deepcopy(dp)
    rules = _raw_mapping(dp)
    if not rules:
        return projected
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


def _validate_consumed_dependency(dp: dict[str, Any]) -> None:
    if dp.get("force") is True or dp.get("persist") is False or dp.get("sensitive") is True:
        raise ConversionError("advanced_mapping_dependency_semantics")
    if set(dp) & {"mask", "mask_signed", "format", "endianness"}:
        raise ConversionError("advanced_mapping_dependency_encoding")


def _prepare_advanced_entity(
    entity: dict[str, Any], platform: str
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], set[int]]:
    by_name = _named_dps(entity, platform)
    advanced_by_dp: dict[str, list[dict[str, Any]]] = {}
    referenced_names: set[str] = set()
    transformed = copy.deepcopy(entity)
    transformed_by_name = _named_dps(transformed, platform)

    for name, original_dp in by_name.items():
        rules = _raw_mapping(original_dp)
        if not any(
            set(rule) & (_ADVANCED_SOURCE_KEYS | _UNSUPPORTED_ADVANCED_KEYS)
            for rule in rules
        ):
            continue
        translated, references = _translate_advanced_mapping(original_dp, by_name)
        if translated:
            advanced_by_dp[str(base._dp_id(original_dp))] = translated
            referenced_names.update(references)
            transformed_by_name[name].clear()
            transformed_by_name[name].update(_project_mapping_for_base(original_dp))

    if not advanced_by_dp:
        return entity, {}, set()

    membership_ids = {int(dp_id) for dp_id in advanced_by_dp}
    for name in referenced_names:
        dependency = by_name[name]
        _validate_consumed_dependency(dependency)
        membership_ids.add(base._dp_id(dependency))

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


def _advanced_wrapper(
    platform: str, converter: Callable[..., base.Converted]
) -> Callable[..., base.Converted]:
    def wrapped(entity: dict[str, Any], *args, **kwargs) -> base.Converted:
        prepared, advanced_by_dp, membership_ids = _prepare_advanced_entity(
            entity, platform
        )
        converted, required, optional = converter(prepared, *args, **kwargs)
        if not advanced_by_dp:
            return converted, required, optional

        converted["config"]["advanced_mapping_by_dp"] = advanced_by_dp
        originals = {base._dp_id(dp): dp for dp in _named_dps(entity, platform).values()}
        for dp_id in membership_ids:
            dp = originals[dp_id]
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


# Extend only the productless conversion surface. Keep the mature product-ID
# importer unchanged while wrapping its converters for Batch F on this module's
# develop-only path.
base.SUPPORTED_PLATFORMS.update({"time", "event"})
_original_converters = dict(base._CONVERTERS)
for _platform, _converter in _original_converters.items():
    base._CONVERTERS[_platform] = _advanced_wrapper(_platform, _converter)

# convert_profile has a special light-scene path that calls _convert_light
# directly rather than through _CONVERTERS, so wrap that reference as well.
if "light" in _original_converters:
    base._convert_light = _advanced_wrapper("light", base._convert_light)

base._CONVERTERS.update({
    "time": _convert_time,
    "event": _convert_event,
})


def convert_profile(*args, **kwargs):
    return base.convert_profile(*args, **kwargs)
