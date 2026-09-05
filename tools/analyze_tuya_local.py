"""Analyze Tuya Local device profiles for LocalTuya catalog compatibility.

This tool is intentionally conservative. A profile is reported as compatible
with the current LocalTuya catalog schema only when it uses a subset that can
be translated without silently dropping Tuya Local semantics.

Usage:
    python tools/analyze_tuya_local.py /path/to/tuya-local
    python tools/analyze_tuya_local.py /path/to/tuya-local --json report.json
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
except ImportError as err:  # pragma: no cover - exercised by CLI environments
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

# These Tuya Local datapoint features carry behaviour that the current
# LocalTuya catalog schema does not model explicitly. Treating them as a
# lossless V1 conversion would therefore be unsafe.
V2_DP_FEATURES = {
    "mapping",
    "hidden",
    "optional",
    "persist",
    "force",
    "readonly",
    "sensitive",
}

# Primitive types that are straightforward to reason about when assessing a
# future converter. Other types may require decoding or platform-specific
# behaviour before they can be represented safely.
V1_SIMPLE_DP_TYPES = {
    "boolean",
    "integer",
    "string",
}


@dataclass(frozen=True, slots=True)
class ProfileAnalysis:
    """Compatibility result for one Tuya Local device profile."""

    file: str
    name: str
    status: str
    product_ids: tuple[str, ...]
    platforms: tuple[str, ...]
    entity_count: int
    dp_count: int
    reasons: tuple[str, ...]


def _product_ids(profile: dict[str, Any]) -> tuple[str, ...]:
    """Return unique non-empty Tuya product IDs from one source profile."""
    result: list[str] = []

    products = profile.get("products", [])
    if not isinstance(products, list):
        return ()

    for product in products:
        if not isinstance(product, dict):
            continue

        product_id = product.get("id")
        if product_id is None:
            continue

        value = str(product_id).strip()
        if value and value not in result:
            result.append(value)

    return tuple(result)


def analyze_profile(
    profile: Any,
    *,
    file_name: str = "<memory>",
) -> ProfileAnalysis:
    """Classify one parsed Tuya Local YAML profile."""
    if not isinstance(profile, dict):
        return ProfileAnalysis(
            file=file_name,
            name="",
            status="invalid",
            product_ids=(),
            platforms=(),
            entity_count=0,
            dp_count=0,
            reasons=("profile_not_object",),
        )

    reasons: set[str] = set()
    product_ids = _product_ids(profile)

    if not product_ids:
        reasons.add("missing_product_id")
    elif len(product_ids) > 1:
        # Schema V1 only carries one product_id per mapping. A future V2 can
        # represent aliases directly rather than duplicating the same mapping.
        reasons.add("multiple_product_ids")

    entities = profile.get("entities")
    if not isinstance(entities, list) or not entities:
        reasons.add("missing_entities")
        entities = []

    platforms: list[str] = []
    dp_count = 0
    unsupported_platform = False
    complex_semantics = False

    for entity in entities:
        if not isinstance(entity, dict):
            reasons.add("invalid_entity")
            continue

        platform = entity.get("entity")
        if not isinstance(platform, str) or not platform.strip():
            reasons.add("missing_entity_platform")
            continue

        platform = platform.strip()
        if platform not in platforms:
            platforms.append(platform)

        if platform not in SUPPORTED_PLATFORMS:
            unsupported_platform = True
            reasons.add(f"unsupported_platform:{platform}")

        dps = entity.get("dps")
        if not isinstance(dps, list) or not dps:
            reasons.add("missing_dps")
            continue

        for dp in dps:
            if not isinstance(dp, dict):
                reasons.add("invalid_dp")
                continue

            dp_count += 1

            if "id" not in dp:
                reasons.add("missing_dp_id")

            dp_type = dp.get("type")
            if isinstance(dp_type, str):
                dp_type = dp_type.strip().lower()
                if dp_type and dp_type not in V1_SIMPLE_DP_TYPES:
                    complex_semantics = True
                    reasons.add(f"complex_dp_type:{dp_type}")
            elif dp_type is not None:
                reasons.add("invalid_dp_type")

            for feature in V2_DP_FEATURES:
                if feature not in dp:
                    continue

                value = dp[feature]

                # Explicit default values should not make a profile complex.
                if feature in {"optional", "force", "readonly", "sensitive", "hidden"}:
                    if value is False:
                        continue
                elif feature == "persist":
                    if value is True:
                        continue

                complex_semantics = True
                reasons.add(f"v2_feature:{feature}")

    if any(
        reason in {
            "profile_not_object",
            "missing_product_id",
            "missing_entities",
            "invalid_entity",
            "missing_entity_platform",
            "missing_dps",
            "invalid_dp",
            "missing_dp_id",
            "invalid_dp_type",
        }
        for reason in reasons
    ):
        status = "invalid"
    elif unsupported_platform:
        status = "unsupported_platform"
    elif complex_semantics or "multiple_product_ids" in reasons:
        status = "needs_v2"
    else:
        status = "convertible_v1"

    return ProfileAnalysis(
        file=file_name,
        name=str(profile.get("name", "")).strip(),
        status=status,
        product_ids=product_ids,
        platforms=tuple(platforms),
        entity_count=len(entities),
        dp_count=dp_count,
        reasons=tuple(sorted(reasons)),
    )


def _devices_dir(source: Path) -> Path:
    """Resolve either a Tuya Local checkout or its devices directory."""
    source = source.expanduser().resolve()

    candidate = (
        source
        / "custom_components"
        / "tuya_local"
        / "devices"
    )
    if candidate.is_dir():
        return candidate

    if source.is_dir() and source.name == "devices":
        return source

    raise FileNotFoundError(
        "Could not find custom_components/tuya_local/devices under "
        f"{source}"
    )


def analyze_source(source: Path) -> list[ProfileAnalysis]:
    """Analyze all Tuya Local YAML device profiles in a checkout."""
    devices_dir = _devices_dir(source)
    results: list[ProfileAnalysis] = []

    for path in sorted(devices_dir.glob("*.yaml")):
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as err:
            results.append(
                ProfileAnalysis(
                    file=path.name,
                    name="",
                    status="invalid",
                    product_ids=(),
                    platforms=(),
                    entity_count=0,
                    dp_count=0,
                    reasons=(f"yaml_error:{type(err).__name__}",),
                )
            )
            continue

        results.append(
            analyze_profile(
                payload,
                file_name=path.name,
            )
        )

    return results


def build_report(results: list[ProfileAnalysis]) -> dict[str, Any]:
    """Build a deterministic machine-readable compatibility report."""
    status_counts = Counter(result.status for result in results)
    reason_counts = Counter(
        reason
        for result in results
        for reason in result.reasons
    )
    platform_counts = Counter(
        platform
        for result in results
        for platform in result.platforms
    )

    return {
        "source": "make-all/tuya-local",
        "target": "MattiaFontana997/localtuya-device-catalog schema v1",
        "profiles": len(results),
        "status_counts": dict(sorted(status_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
        "platform_counts": dict(sorted(platform_counts.items())),
        "results": [asdict(result) for result in results],
    }


def _print_summary(report: dict[str, Any]) -> None:
    """Print a compact human-readable report."""
    print(f"Profiles analyzed: {report['profiles']}")
    print("Status:")
    for status, count in report["status_counts"].items():
        print(f"  {status}: {count}")

    if report["reason_counts"]:
        print("Top blockers/features:")
        ranked = sorted(
            report["reason_counts"].items(),
            key=lambda item: (-item[1], item[0]),
        )
        for reason, count in ranked[:20]:
            print(f"  {reason}: {count}")


def main() -> int:
    """Run the CLI."""
    parser = argparse.ArgumentParser(
        description=(
            "Analyze make-all/tuya-local device YAML files for compatibility "
            "with the current LocalTuya community catalog schema."
        )
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Path to a tuya-local checkout or its devices directory",
    )
    parser.add_argument(
        "--json",
        type=Path,
        dest="json_output",
        help="Optional path for the full JSON report",
    )
    args = parser.parse_args()

    results = analyze_source(args.source)
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
