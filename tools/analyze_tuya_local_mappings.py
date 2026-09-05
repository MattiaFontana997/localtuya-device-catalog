"""Analyze Tuya Local mapping-rule shapes for LocalTuya porting.

The compatibility analyzer tells us *that* a profile uses mapping rules. This
second-stage tool tells us *which kind* of mapping rules are used so Catalog V2
can be designed from measured upstream behaviour rather than assumptions.

Usage:
    python tools/analyze_tuya_local_mappings.py /path/to/tuya-local
    python tools/analyze_tuya_local_mappings.py /path/to/tuya-local \
        --json mapping-analysis.json
"""

from __future__ import annotations

import argparse
import json
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


SUPPORTED_PLATFORMS = {
    "binary_sensor",
    "climate",
    "cover",
    "fan",
    "light",
    "number",
    "select",
    "sensor",
    "switch",
    "vacuum",
}

# Mapping keys documented by make-all/tuya-local. Keeping this explicit lets
# the report flag new upstream semantics instead of silently treating them as
# understood.
KNOWN_RULE_KEYS = {
    "available",
    "conditions",
    "constraint",
    "default",
    "dps_val",
    "hidden",
    "icon",
    "icon_priority",
    "invalid",
    "invert",
    "mapping",
    "range",
    "scale",
    "step",
    "target_range",
    "value",
    "value_mirror",
    "value_redirect",
}

# These rules depend only on the current DP and can in principle be compiled
# into LocalTuya entity configuration without adding cross-DP runtime logic.
STATIC_RULE_KEYS = {
    "default",
    "dps_val",
    "hidden",
    "icon",
    "icon_priority",
    "invert",
    "range",
    "scale",
    "step",
    "target_range",
    "value",
}

ADVANCED_RULE_KEYS = {
    "available",
    "conditions",
    "constraint",
    "invalid",
    "mapping",
    "value_mirror",
    "value_redirect",
}


@dataclass(frozen=True, slots=True)
class ProfileMappingAnalysis:
    """Mapping-rule summary for one Tuya Local profile."""

    file: str
    name: str
    platforms: tuple[str, ...]
    supported_platforms_only: bool
    mapping_dp_count: int
    mapping_rule_count: int
    classification: str
    rule_keys: tuple[str, ...]
    advanced_keys: tuple[str, ...]
    unknown_keys: tuple[str, ...]


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


def _iter_rule_dicts(mapping: Any):
    """Yield mapping/condition rule dictionaries recursively."""
    if not isinstance(mapping, list):
        return

    for rule in mapping:
        if not isinstance(rule, dict):
            continue
        yield rule

        conditions = rule.get("conditions")
        if isinstance(conditions, list):
            for condition in conditions:
                if not isinstance(condition, dict):
                    continue
                yield condition
                nested = condition.get("mapping")
                if isinstance(nested, list):
                    yield from _iter_rule_dicts(nested)

        nested = rule.get("mapping")
        if isinstance(nested, list):
            yield from _iter_rule_dicts(nested)


def _platforms(profile: dict[str, Any]) -> tuple[str, ...]:
    result: list[str] = []
    entities = profile.get("entities", [])
    if not isinstance(entities, list):
        return ()

    for entity in entities:
        if not isinstance(entity, dict):
            continue
        platform = entity.get("entity")
        if not isinstance(platform, str):
            continue
        platform = platform.strip()
        if platform and platform not in result:
            result.append(platform)
    return tuple(result)


def analyze_profile(
    profile: Any,
    *,
    file_name: str = "<memory>",
) -> ProfileMappingAnalysis:
    if not isinstance(profile, dict):
        return ProfileMappingAnalysis(
            file=file_name,
            name="",
            platforms=(),
            supported_platforms_only=False,
            mapping_dp_count=0,
            mapping_rule_count=0,
            classification="invalid",
            rule_keys=(),
            advanced_keys=(),
            unknown_keys=(),
        )

    platforms = _platforms(profile)
    entities = profile.get("entities", [])
    mapping_dp_count = 0
    mapping_rule_count = 0
    rule_keys: set[str] = set()
    advanced_keys: set[str] = set()
    unknown_keys: set[str] = set()

    if isinstance(entities, list):
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            dps = entity.get("dps", [])
            if not isinstance(dps, list):
                continue
            for dp in dps:
                if not isinstance(dp, dict):
                    continue
                mapping = dp.get("mapping")
                if not isinstance(mapping, list):
                    continue

                mapping_dp_count += 1
                for rule in _iter_rule_dicts(mapping):
                    mapping_rule_count += 1
                    keys = {str(key) for key in rule}
                    rule_keys.update(keys)
                    advanced_keys.update(keys & ADVANCED_RULE_KEYS)
                    unknown_keys.update(keys - KNOWN_RULE_KEYS)

    if mapping_dp_count == 0:
        classification = "no_mapping"
    elif unknown_keys:
        classification = "unknown_semantics"
    elif advanced_keys:
        classification = "advanced_mapping"
    elif rule_keys.issubset(STATIC_RULE_KEYS):
        classification = "static_mapping"
    else:
        classification = "advanced_mapping"

    return ProfileMappingAnalysis(
        file=file_name,
        name=str(profile.get("name", "")).strip(),
        platforms=platforms,
        supported_platforms_only=bool(platforms)
        and set(platforms).issubset(SUPPORTED_PLATFORMS),
        mapping_dp_count=mapping_dp_count,
        mapping_rule_count=mapping_rule_count,
        classification=classification,
        rule_keys=tuple(sorted(rule_keys)),
        advanced_keys=tuple(sorted(advanced_keys)),
        unknown_keys=tuple(sorted(unknown_keys)),
    )


def analyze_source(source: Path) -> list[ProfileMappingAnalysis]:
    devices_dir = _devices_dir(source)
    results: list[ProfileMappingAnalysis] = []

    for path in sorted(devices_dir.glob("*.yaml")):
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            results.append(
                ProfileMappingAnalysis(
                    file=path.name,
                    name="",
                    platforms=(),
                    supported_platforms_only=False,
                    mapping_dp_count=0,
                    mapping_rule_count=0,
                    classification="invalid",
                    rule_keys=(),
                    advanced_keys=(),
                    unknown_keys=(),
                )
            )
            continue
        results.append(analyze_profile(payload, file_name=path.name))

    return results


def build_report(results: list[ProfileMappingAnalysis]) -> dict[str, Any]:
    mapping_results = [result for result in results if result.mapping_dp_count]
    supported_mapping_results = [
        result for result in mapping_results if result.supported_platforms_only
    ]

    classification_counts = Counter(
        result.classification for result in mapping_results
    )
    supported_classification_counts = Counter(
        result.classification for result in supported_mapping_results
    )
    rule_key_counts = Counter(
        key for result in mapping_results for key in result.rule_keys
    )
    advanced_key_counts = Counter(
        key for result in mapping_results for key in result.advanced_keys
    )
    unknown_key_counts = Counter(
        key for result in mapping_results for key in result.unknown_keys
    )

    shape_counts = Counter(
        ",".join(result.rule_keys) for result in mapping_results
    )

    return {
        "source": "make-all/tuya-local",
        "profiles": len(results),
        "profiles_with_mapping": len(mapping_results),
        "supported_platform_profiles_with_mapping": len(
            supported_mapping_results
        ),
        "classification_counts": dict(sorted(classification_counts.items())),
        "supported_platform_classification_counts": dict(
            sorted(supported_classification_counts.items())
        ),
        "rule_key_profile_counts": dict(sorted(rule_key_counts.items())),
        "advanced_key_profile_counts": dict(sorted(advanced_key_counts.items())),
        "unknown_key_profile_counts": dict(sorted(unknown_key_counts.items())),
        "top_rule_key_shapes": [
            {"keys": shape, "profiles": count}
            for shape, count in sorted(
                shape_counts.items(), key=lambda item: (-item[1], item[0])
            )[:30]
        ],
        "results": [asdict(result) for result in results],
    }


def _print_summary(report: dict[str, Any]) -> None:
    print(f"Profiles analyzed: {report['profiles']}")
    print(f"Profiles with mapping: {report['profiles_with_mapping']}")
    print(
        "Supported-platform profiles with mapping: "
        f"{report['supported_platform_profiles_with_mapping']}"
    )
    print("Mapping classes:")
    for key, value in report["classification_counts"].items():
        print(f"  {key}: {value}")
    print("Supported-platform mapping classes:")
    for key, value in report[
        "supported_platform_classification_counts"
    ].items():
        print(f"  {key}: {value}")
    print("Advanced mapping features:")
    ranked = sorted(
        report["advanced_key_profile_counts"].items(),
        key=lambda item: (-item[1], item[0]),
    )
    for key, value in ranked:
        print(f"  {key}: {value}")
    if report["unknown_key_profile_counts"]:
        print("Unknown mapping keys:")
        for key, value in report["unknown_key_profile_counts"].items():
            print(f"  {key}: {value}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze Tuya Local mapping-rule shapes for LocalTuya porting."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--json", type=Path, dest="json_output")
    args = parser.parse_args()

    report = build_report(analyze_source(args.source))
    _print_summary(report)

    if args.json_output is not None:
        args.json_output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
