#!/usr/bin/env python3
"""Reject ambiguous community promotions before catalog mutation."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAPPING_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}$")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")

    return data


def _selector(mapping: dict[str, Any]) -> tuple[str, str | None, tuple[int, ...]]:
    match = mapping.get("match")
    if not isinstance(match, dict):
        raise ValueError("Mapping is missing a valid match object")

    product_id = match.get("product_id")
    if not isinstance(product_id, str) or not product_id:
        raise ValueError("Mapping is missing product_id")

    category = match.get("category")
    if category is not None and not isinstance(category, str):
        raise ValueError("Mapping category must be a string when present")

    required_dps = match.get("required_dps")
    if not isinstance(required_dps, list):
        raise ValueError("Mapping required_dps must be a list")

    try:
        normalized_dps = tuple(sorted({int(dp) for dp in required_dps}))
    except (TypeError, ValueError) as exc:
        raise ValueError("Mapping required_dps contains an invalid DP") from exc

    return product_id, category, normalized_dps


def ensure_no_catalog_selector_duplicate(root: Path, mapping_id: str) -> None:
    """Reject promotion when catalog already owns the same match selector."""
    if not MAPPING_ID_RE.fullmatch(mapping_id):
        raise ValueError("Invalid mapping ID")

    submission_path = root / "submissions" / f"{mapping_id}.json"
    if not submission_path.is_file():
        raise ValueError(f"Experimental submission not found: {submission_path}")

    submission = _load_json(submission_path)
    mappings = submission.get("mappings")
    if (
        not isinstance(mappings, list)
        or len(mappings) != 1
        or not isinstance(mappings[0], dict)
    ):
        raise ValueError("Submission must contain exactly one mapping")

    candidate = mappings[0]
    if candidate.get("id") != mapping_id:
        raise ValueError("Submission mapping ID does not match its filename")

    candidate_selector = _selector(candidate)

    catalog = _load_json(root / "catalog.json")
    catalog_mappings = catalog.get("mappings", [])
    if not isinstance(catalog_mappings, list):
        raise ValueError("catalog.json mappings must be a list")

    for existing in catalog_mappings:
        if not isinstance(existing, dict):
            continue
        if _selector(existing) != candidate_selector:
            continue

        existing_id = existing.get("id", "<unknown>")
        existing_confidence = existing.get("confidence", "<unknown>")
        raise ValueError(
            "Catalog already contains mapping "
            f"{existing_id!r} with the same product/category/required_dps "
            f"selector at confidence {existing_confidence!r}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check whether a community promotion would duplicate a catalog selector"
    )
    parser.add_argument("--mapping-id", required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    try:
        ensure_no_catalog_selector_duplicate(
            args.root.resolve(),
            args.mapping_id,
        )
    except ValueError as exc:
        parser.error(str(exc))

    print(f"Promotion candidate {args.mapping_id} has no catalog selector duplicate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
