"""Extra lossless converters enabled for productless Catalog V3 imports.

The product-ID importer intentionally stays conservative and stable. Productless
fingerprints can opt into runtime capabilities added after that importer was
written, but only through explicit converters in this module.
"""

from __future__ import annotations

from typing import Any

import import_tuya_local as base


ConversionError = base.ConversionError
SOURCE_LICENSE = base.SOURCE_LICENSE
SOURCE_REPOSITORY = base.SOURCE_REPOSITORY
_devices_dir = base._devices_dir
_product_ids = base._product_ids
_platforms = base._platforms


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

    # Tuya Local currently does not write its hms DP in async_set_value. Importing
    # hms as writable would therefore claim behaviour the source profile itself
    # does not provide. Keep this first tranche to integer components only.
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

    # Availability follows a required functional DP whenever one exists.
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

    # Validate generic entity metadata, but do not copy its generic device_class
    # key because Event uses event_device_class at runtime.
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


# Extend only the productless conversion surface. The underlying base converter
# still performs all atomic profile validation, required/optional DP accounting,
# provenance generation and duplicate-core-entity checks.
base.SUPPORTED_PLATFORMS.update({"time", "event"})
base._CONVERTERS.update({
    "time": _convert_time,
    "event": _convert_event,
})


def convert_profile(*args, **kwargs):
    return base.convert_profile(*args, **kwargs)
