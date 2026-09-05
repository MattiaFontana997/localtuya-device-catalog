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
from typing import Any

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


def _convert_switch(entity: dict[str, Any]) -> tuple[dict[str, Any], int, bool]:
    dp = _single_named_dp(entity, "switch")
    _check_common_dp_semantics(dp, writable=True)
    if _dp_type(dp) != "boolean":
        raise ConversionError("switch_non_boolean")

    rules = _mapping_rules(dp)
    if rules:
        expected = {False: False, True: True}
        observed: dict[bool, bool] = {}
        for rule in rules:
            if set(rule) != {"dps_val", "value"}:
                raise ConversionError("switch_non_identity_mapping")
            raw = rule["dps_val"]
            value = rule["value"]
            if not isinstance(raw, bool) or not isinstance(value, bool):
                raise ConversionError("switch_non_identity_mapping")
            observed[raw] = value
        if observed != expected:
            raise ConversionError("switch_non_identity_mapping")

    dp_id = _dp_id(dp)
    config: dict[str, Any] = {
        "id": dp_id,
        "platform": "switch",
        "restore_on_reconnect": False,
        "is_passive_entity": False,
    }
    _entity_metadata(entity, config)
    return {"platform": "switch", "config": config}, dp_id, bool(dp.get("optional"))


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


def _convert_binary_sensor(
    entity: dict[str, Any],
) -> tuple[dict[str, Any], int, bool]:
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
    return (
        {"platform": "binary_sensor", "config": config},
        dp_id,
        bool(dp.get("optional")),
    )


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


def _convert_sensor(entity: dict[str, Any]) -> tuple[dict[str, Any], int, bool]:
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
    return {"platform": "sensor", "config": config}, dp_id, bool(dp.get("optional"))


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


def _convert_number(entity: dict[str, Any]) -> tuple[dict[str, Any], int, bool]:
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
    return {"platform": "number", "config": config}, dp_id, bool(dp.get("optional"))


def _convert_select(entity: dict[str, Any]) -> tuple[dict[str, Any], int, bool]:
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
    return {"platform": "select", "config": config}, dp_id, bool(dp.get("optional"))


_CONVERTERS = {
    "binary_sensor": _convert_binary_sensor,
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

    for entity in entities:
        if not isinstance(entity, dict):
            raise ConversionError("invalid_entity")
        platform = entity.get("entity")
        if platform not in SUPPORTED_PLATFORMS:
            raise ConversionError(f"unsupported_platform:{platform}")

        converted, dp_id, optional = _CONVERTERS[platform](entity)
        converted_entities.append(converted)
        if optional:
            optional_dps.add(dp_id)
        else:
            required_dps.add(dp_id)

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
