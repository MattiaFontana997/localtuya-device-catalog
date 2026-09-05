#!/usr/bin/env python3
"""Validate LocalTuya community catalog and submissions."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]

SCHEMA_PATH = ROOT / "schema" / "catalog.schema.json"
CATALOG_PATH = ROOT / "catalog.json"
SUBMISSIONS_PATH = ROOT / "submissions"

SENSITIVE_KEYS = {
    "local_key",
    "device_id",
    "host",
    "ip",
    "gwid",
    "client_id",
    "client_secret",
    "user_id",
    "username",
    "region",
}

PROTECTED_OVERRIDE_KEYS = {
    "id",
    "platform",
    "friendly_name",
}

DP_REFERENCE_KEYS = {
    "id",
    "brightness",
    "color_temp",
    "color_mode",
    "color",
    "scene",
    "effect",
    "current",
    "current_consumption",
    "voltage",
    "fan_speed_control",
    "fan_oscillating_control",
    "fan_direction",
}


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc


def find_sensitive_keys(value: Any, path: str = "$") -> list[str]:
    result: list[str] = []

    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            child_path = f"{path}.{key}"

            if normalized in SENSITIVE_KEYS:
                result.append(child_path)

            result.extend(find_sensitive_keys(child, child_path))

    elif isinstance(value, list):
        for index, child in enumerate(value):
            result.extend(find_sensitive_keys(child, f"{path}[{index}]"))

    return result


def is_dp_reference_key(key: str) -> bool:
    return key in DP_REFERENCE_KEYS or key.endswith("_dp")


def collect_config_dps(config: dict[str, Any]) -> set[int]:
    result: set[int] = set()

    for key, value in config.items():
        if not is_dp_reference_key(str(key)):
            continue

        if isinstance(value, bool):
            continue

        try:
            dp_id = int(value)
        except (TypeError, ValueError):
            continue

        if dp_id > 0:
            result.add(dp_id)

    return result


def safe_mapping_id_part(value: str) -> str:
    """Create the canonical mapping ID product fragment."""
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return value or "tuya-product"


def expected_mapping_id(mapping: dict[str, Any]) -> str:
    """Return the deterministic ID expected for a submission mapping."""
    mapping_without_id = {
        key: value for key, value in mapping.items() if key != "id"
    }

    canonical = json.dumps(
        mapping_without_id,
        sort_keys=True,
        separators=(",", ":"),
    )

    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:10]

    product_ids = mapping["match"]["product_ids"]
    primary_product_id = sorted(str(value) for value in product_ids)[0]

    return f"{safe_mapping_id_part(primary_product_id)}-{digest}"


def _validate_sorted_unique(
    values: list[Any],
    *,
    source: Path,
    mapping_id: str,
    field: str,
) -> list[str]:
    """Require deterministic ordering for arrays that form mapping identity."""
    if values != sorted(values):
        return [
            f"{source}: mapping {mapping_id!r} {field} must be sorted"
        ]
    return []


def validate_semantics(data: dict[str, Any], source: Path) -> list[str]:
    errors: list[str] = []

    sensitive = find_sensitive_keys(data)
    for field in sensitive:
        errors.append(f"{source}: forbidden sensitive field {field}")

    mappings = data.get("mappings", [])
    is_submission = source.parent.name == "submissions"

    if is_submission:
        if len(mappings) != 1:
            errors.append(f"{source}: submission must contain exactly one mapping")

        elif isinstance(mappings[0], dict):
            mapping = mappings[0]
            mapping_id = mapping.get("id")

            if isinstance(mapping_id, str):
                expected_filename = f"{mapping_id}.json"
                if source.name != expected_filename:
                    errors.append(
                        f"{source}: submission filename must be "
                        f"{expected_filename!r}"
                    )

                try:
                    canonical_id = expected_mapping_id(mapping)
                except (KeyError, TypeError, ValueError, IndexError):
                    canonical_id = None

                if canonical_id is not None and mapping_id != canonical_id:
                    errors.append(
                        f"{source}: mapping id {mapping_id!r} does not match "
                        f"its canonical content id {canonical_id!r}"
                    )

        fingerprint = data.get("fingerprint")

        if not isinstance(fingerprint, dict):
            errors.append(f"{source}: submission is missing fingerprint")
        else:
            declared_required = set(fingerprint.get("required_dps", []))
            declared_optional = set(fingerprint.get("optional_dps", []))
            mapping_required: set[int] = set()
            mapping_optional: set[int] = set()

            for mapping in mappings:
                mapping_required.update(mapping["match"]["required_dps"])
                mapping_optional.update(mapping["match"]["optional_dps"])

            if declared_required != mapping_required:
                errors.append(
                    f"{source}: fingerprint required_dps does not match "
                    "mapping required_dps"
                )

            if declared_optional != mapping_optional:
                errors.append(
                    f"{source}: fingerprint optional_dps does not match "
                    "mapping optional_dps"
                )

            if fingerprint.get("entity_count") != sum(
                len(mapping["entities"]) for mapping in mappings
            ):
                errors.append(
                    f"{source}: fingerprint entity_count does not match entities"
                )

    elif "fingerprint" in data:
        errors.append(f"{source}: catalog.json must not contain fingerprint")

    mapping_ids: set[str] = set()

    for mapping in mappings:
        mapping_id = mapping["id"]

        if mapping_id in mapping_ids:
            errors.append(f"{source}: duplicate mapping id {mapping_id!r}")
        mapping_ids.add(mapping_id)

        match = mapping["match"]
        product_ids = match["product_ids"]
        required_dps = set(match["required_dps"])
        optional_dps = set(match["optional_dps"])

        errors.extend(
            _validate_sorted_unique(
                product_ids,
                source=source,
                mapping_id=mapping_id,
                field="product_ids",
            )
        )
        errors.extend(
            _validate_sorted_unique(
                match["required_dps"],
                source=source,
                mapping_id=mapping_id,
                field="required_dps",
            )
        )
        errors.extend(
            _validate_sorted_unique(
                match["optional_dps"],
                source=source,
                mapping_id=mapping_id,
                field="optional_dps",
            )
        )

        if any(product_id != product_id.strip() for product_id in product_ids):
            errors.append(
                f"{source}: mapping {mapping_id!r} product_ids must not "
                "contain leading or trailing whitespace"
            )

        overlap = required_dps & optional_dps
        if overlap:
            errors.append(
                f"{source}: mapping {mapping_id!r} DPS cannot be both required "
                f"and optional: {sorted(overlap)}"
            )

        if not required_dps:
            errors.append(
                f"{source}: mapping {mapping_id!r} has no required_dps"
            )

        entity_keys: set[tuple[str, int]] = set()
        referenced_dps: set[int] = set()

        for entity in mapping["entities"]:
            platform = entity["platform"]
            config = entity["config"]
            override_keys = entity.get("override_keys", [])

            for override_key in override_keys:
                normalized_override = str(override_key).strip().lower()

                if normalized_override in PROTECTED_OVERRIDE_KEYS:
                    errors.append(
                        f"{source}: mapping {mapping_id!r} attempts protected "
                        f"override {override_key!r}"
                    )

                if normalized_override in SENSITIVE_KEYS:
                    errors.append(
                        f"{source}: mapping {mapping_id!r} attempts sensitive "
                        f"override {override_key!r}"
                    )

                if override_key not in config:
                    errors.append(
                        f"{source}: mapping {mapping_id!r} override key "
                        f"{override_key!r} is missing from entity config"
                    )

            if config.get("platform") != platform:
                errors.append(
                    f"{source}: mapping {mapping_id!r} entity platform mismatch: "
                    f"{platform!r} vs {config.get('platform')!r}"
                )

            primary_dp = config["id"]
            entity_key = (platform, primary_dp)

            if entity_key in entity_keys:
                errors.append(
                    f"{source}: mapping {mapping_id!r} duplicates {platform} "
                    f"DP {primary_dp}"
                )
            entity_keys.add(entity_key)
            referenced_dps.update(collect_config_dps(config))

        declared_dps = required_dps | optional_dps
        missing = referenced_dps - declared_dps

        if missing:
            errors.append(
                f"{source}: mapping {mapping_id!r} references DPS missing from "
                f"required_dps/optional_dps: {sorted(missing)}"
            )

    return errors


def validate_document(path: Path, schema: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    try:
        data = load_json(path)
    except ValueError as exc:
        return [str(exc)]

    validator = Draft202012Validator(schema)

    for error in sorted(
        validator.iter_errors(data),
        key=lambda item: list(item.absolute_path),
    ):
        json_path = "$" + "".join(
            f"[{part}]" if isinstance(part, int) else f".{part}"
            for part in error.absolute_path
        )
        errors.append(f"{path}: {json_path}: {error.message}")

    if errors:
        return errors

    errors.extend(validate_semantics(data, path))
    return errors


def main() -> int:
    schema = load_json(SCHEMA_PATH)
    files = [CATALOG_PATH]

    if SUBMISSIONS_PATH.exists():
        files.extend(sorted(SUBMISSIONS_PATH.glob("*.json")))

    all_errors: list[str] = []

    for path in files:
        errors = validate_document(path, schema)

        if errors:
            all_errors.extend(errors)
        else:
            print(f"OK: {path.relative_to(ROOT)}")

    if all_errors:
        print("\nValidation failed:", file=sys.stderr)
        for error in all_errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"\nAll {len(files)} catalog document(s) are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
