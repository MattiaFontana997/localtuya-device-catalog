#!/usr/bin/env python3
"""Validate LocalTuya community catalog and submissions."""

from __future__ import annotations

import json
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

DP_REFERENCE_KEYS = {
    "id",
    "brightness",
    "color_temp",
    "color_mode",
    "color",
    "scene",
    "current",
    "current_consumption",
    "voltage",
    "fan_speed_control",
    "fan_oscillating_control",
    "fan_direction",
}


def load_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{path}: invalid JSON: {exc}"
        ) from exc


def find_sensitive_keys(
    value: Any,
    path: str = "$",
) -> list[str]:
    result: list[str] = []

    if isinstance(value, dict):
        for key, child in value.items():
            normalized = (
                str(key)
                .strip()
                .lower()
            )

            child_path = (
                f"{path}.{key}"
            )

            if normalized in SENSITIVE_KEYS:
                result.append(child_path)

            result.extend(
                find_sensitive_keys(
                    child,
                    child_path,
                )
            )

    elif isinstance(value, list):
        for index, child in enumerate(value):
            result.extend(
                find_sensitive_keys(
                    child,
                    f"{path}[{index}]",
                )
            )

    return result


def is_dp_reference_key(
    key: str,
) -> bool:
    return (
        key in DP_REFERENCE_KEYS
        or key.endswith("_dp")
    )


def collect_config_dps(
    config: dict[str, Any],
) -> set[int]:
    result: set[int] = set()

    for key, value in config.items():
        if not is_dp_reference_key(
            str(key)
        ):
            continue

        if isinstance(value, bool):
            continue

        try:
            dp_id = int(value)
        except (
            TypeError,
            ValueError,
        ):
            continue

        if dp_id > 0:
            result.add(dp_id)

    return result


def validate_semantics(
    data: dict[str, Any],
    source: Path,
) -> list[str]:
    errors: list[str] = []

    sensitive = find_sensitive_keys(
        data
    )

    for field in sensitive:
        errors.append(
            f"{source}: forbidden sensitive field {field}"
        )

    mappings = data.get(
        "mappings",
        [],
    )

    mapping_ids: set[str] = set()

    for index, mapping in enumerate(
        mappings
    ):
        mapping_id = mapping["id"]

        if mapping_id in mapping_ids:
            errors.append(
                f"{source}: duplicate mapping id "
                f"{mapping_id!r}"
            )

        mapping_ids.add(mapping_id)

        required_dps = set(
            mapping["match"][
                "required_dps"
            ]
        )

        if not required_dps:
            errors.append(
                f"{source}: mapping {mapping_id!r} "
                "has no required_dps"
            )

        entity_keys: set[
            tuple[str, int]
        ] = set()

        referenced_dps: set[int] = set()

        for entity in mapping[
            "entities"
        ]:
            platform = entity[
                "platform"
            ]

            config = entity[
                "config"
            ]

            if (
                config.get("platform")
                != platform
            ):
                errors.append(
                    f"{source}: mapping {mapping_id!r} "
                    f"entity platform mismatch: "
                    f"{platform!r} vs "
                    f"{config.get('platform')!r}"
                )

            primary_dp = config["id"]

            entity_key = (
                platform,
                primary_dp,
            )

            if entity_key in entity_keys:
                errors.append(
                    f"{source}: mapping {mapping_id!r} "
                    f"duplicates {platform} DP "
                    f"{primary_dp}"
                )

            entity_keys.add(entity_key)

            referenced_dps.update(
                collect_config_dps(
                    config
                )
            )

        missing = (
            referenced_dps
            - required_dps
        )

        if missing:
            errors.append(
                f"{source}: mapping {mapping_id!r} "
                "references DPS missing from "
                f"required_dps: {sorted(missing)}"
            )

    return errors


def validate_document(
    path: Path,
    schema: dict[str, Any],
) -> list[str]:
    errors: list[str] = []

    try:
        data = load_json(path)
    except ValueError as exc:
        return [str(exc)]

    validator = Draft202012Validator(
        schema
    )

    for error in sorted(
        validator.iter_errors(data),
        key=lambda item: list(
            item.absolute_path
        ),
    ):
        json_path = (
            "$"
            + "".join(
                (
                    f"[{part}]"
                    if isinstance(
                        part,
                        int,
                    )
                    else f".{part}"
                )
                for part
                in error.absolute_path
            )
        )

        errors.append(
            f"{path}: {json_path}: "
            f"{error.message}"
        )

    if errors:
        return errors

    errors.extend(
        validate_semantics(
            data,
            path,
        )
    )

    return errors


def main() -> int:
    schema = load_json(
        SCHEMA_PATH
    )

    files = [
        CATALOG_PATH,
    ]

    if SUBMISSIONS_PATH.exists():
        files.extend(
            sorted(
                SUBMISSIONS_PATH.glob(
                    "*.json"
                )
            )
        )

    all_errors: list[str] = []

    for path in files:
        errors = validate_document(
            path,
            schema,
        )

        if errors:
            all_errors.extend(errors)
        else:
            print(
                f"OK: {path.relative_to(ROOT)}"
            )

    if all_errors:
        print(
            "\nValidation failed:",
            file=sys.stderr,
        )

        for error in all_errors:
            print(
                f"- {error}",
                file=sys.stderr,
            )

        return 1

    print(
        f"\nAll {len(files)} catalog "
        "document(s) are valid."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
