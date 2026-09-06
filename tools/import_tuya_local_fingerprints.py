"""Import productless Tuya Local profiles as fail-closed DPS fingerprints.

This is deliberately separate from the product-ID importer. It reuses the
lossless platform conversion logic, plus explicitly reviewed productless-only
converters for newer LocalTuya runtimes. Productless output is never considered
verified and is only usable by LocalTuya's schema-v3 exact-DPS matcher.

A generated fingerprint says only: all required DPS are present and every
observed LAN DP is explained by required+optional DPS. Runtime matching also
rejects equal-best ambiguous fingerprints.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as err:  # pragma: no cover
    raise SystemExit("PyYAML is required: python -m pip install 'PyYAML>=6,<7'") from err

from import_tuya_local_productless import (
    ConversionError,
    SOURCE_LICENSE,
    SOURCE_REPOSITORY,
    _devices_dir,
    _product_ids,
    _platforms,
    convert_profile,
)


@dataclass(frozen=True, slots=True)
class FingerprintImportResult:
    file: str
    name: str
    status: str
    mapping_id: str | None
    platforms: tuple[str, ...]
    reasons: tuple[str, ...]


def _fingerprint_id(source_file: str, mapping: dict[str, Any]) -> str:
    material = {
        "source_file": source_file,
        "required_dps": mapping["match"]["required_dps"],
        "optional_dps": mapping["match"]["optional_dps"],
        "entities": mapping["entities"],
    }
    digest = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:10]
    stem = Path(source_file).stem
    safe = "".join(c if c.isalnum() or c in "._-" else "-" for c in stem).strip("-")
    return f"fingerprint-{safe or 'tuya-profile'}-{digest}"


def convert_productless_profile(
    profile: Any,
    *,
    source_file: str,
    revision: str | None = None,
) -> dict[str, Any]:
    """Convert one no-product profile using reviewed lossless converters."""
    if not isinstance(profile, dict):
        raise ConversionError("profile_not_object")
    if _product_ids(profile):
        raise ConversionError("has_product_id")

    # Reuse the mature V2 converter without weakening its product-ID guard.
    # The synthetic ID exists only in this in-memory copy and is stripped from
    # output before returning.
    synthetic = copy.deepcopy(profile)
    synthetic["products"] = [{"id": "fingerprint-import-placeholder"}]
    mapping = convert_profile(
        synthetic,
        source_file=source_file,
        revision=revision,
    )

    mapping["match"]["product_ids"] = []
    mapping["match"]["fingerprint"] = {"mode": "exact_dps"}
    mapping["confidence"] = "experimental"
    mapping["id"] = _fingerprint_id(source_file, mapping)

    provenance = mapping.setdefault("provenance", {})
    provenance["source"] = SOURCE_REPOSITORY
    provenance["license"] = SOURCE_LICENSE
    provenance["path"] = f"custom_components/tuya_local/devices/{source_file}"
    if revision:
        provenance["revision"] = revision
    return mapping


def analyze_source(
    source: Path,
    *,
    revision: str | None = None,
    output_dir: Path | None = None,
) -> tuple[list[FingerprintImportResult], list[dict[str, Any]]]:
    devices_dir = _devices_dir(source)
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
    results: list[FingerprintImportResult] = []
    mappings: list[dict[str, Any]] = []

    for path in sorted(devices_dir.glob("*.yaml")):
        try:
            profile = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as err:
            results.append(FingerprintImportResult(
                path.name, "", "skipped", None, (),
                (f"yaml_error:{type(err).__name__}",),
            ))
            continue

        profile_dict = profile if isinstance(profile, dict) else {}
        name = str(profile_dict.get("name", "")).strip()
        platforms = tuple(_platforms(profile_dict))
        if _product_ids(profile_dict):
            results.append(FingerprintImportResult(
                path.name, name, "not_productless", None, platforms, ("has_product_id",)
            ))
            continue
        try:
            mapping = convert_productless_profile(
                profile, source_file=path.name, revision=revision
            )
        except ConversionError as err:
            results.append(FingerprintImportResult(
                path.name, name, "skipped", None, platforms, (str(err),)
            ))
            continue

        mappings.append(mapping)
        results.append(FingerprintImportResult(
            path.name, name, "convertible_fingerprint", mapping["id"], platforms, ()
        ))
        if output_dir is not None:
            payload = {"schema_version": 3, "mappings": [mapping]}
            (output_dir / f"{mapping['id']}.json").write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
    return results, mappings


def build_report(results: list[FingerprintImportResult]) -> dict[str, Any]:
    return {
        "source": SOURCE_REPOSITORY,
        "target_schema": 3,
        "profiles": len(results),
        "status_counts": dict(sorted(Counter(r.status for r in results).items())),
        "reason_counts": dict(sorted(Counter(reason for r in results for reason in r.reasons).items())),
        "results": [asdict(result) for result in results],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert productless Tuya Local profiles to safe schema-v3 fingerprints.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--revision")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--json", type=Path, dest="json_output")
    args = parser.parse_args()
    results, mappings = analyze_source(
        args.source, revision=args.revision, output_dir=args.output_dir
    )
    report = build_report(results)
    print(f"Profiles analyzed: {report['profiles']}")
    for status, count in report["status_counts"].items():
        print(f"  {status}: {count}")
    print(f"Safe fingerprint candidates: {len(mappings)}")
    if args.json_output is not None:
        args.json_output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
