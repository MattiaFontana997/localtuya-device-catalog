#!/usr/bin/env python3
"""Promote LocalTuya catalog mappings through trusted stages."""

from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

MAPPING_ID_RE = re.compile(
    r"^[A-Za-z0-9._-]{1,160}$"
)

TARGETS = {
    "community",
    "verified",
}


def _load_json(
    path: Path,
) -> dict[str, Any]:
    """Load one JSON document."""
    try:
        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError(
            f"Unable to read {path}: {exc}"
        ) from exc

    if not isinstance(
        data,
        dict,
    ):
        raise ValueError(
            f"{path} must contain a JSON object"
        )

    return data


def _save_json(
    path: Path,
    data: dict[str, Any],
) -> None:
    """Write deterministic human-readable JSON."""
    path.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _catalog_mapping(
    catalog: dict[str, Any],
    mapping_id: str,
) -> dict[str, Any] | None:
    """Find a mapping already present in catalog.json."""
    mappings = catalog.get(
        "mappings",
        [],
    )

    if not isinstance(
        mappings,
        list,
    ):
        raise ValueError(
            "catalog.json mappings must be a list"
        )

    for mapping in mappings:
        if (
            isinstance(
                mapping,
                dict,
            )
            and mapping.get("id")
            == mapping_id
        ):
            return mapping

    return None


def promote_mapping(
    root: Path,
    mapping_id: str,
    target: str,
) -> tuple[str, str]:
    """Promote one mapping to the next allowed trust stage."""
    if not MAPPING_ID_RE.fullmatch(
        mapping_id
    ):
        raise ValueError(
            "Invalid mapping ID"
        )

    if target not in TARGETS:
        raise ValueError(
            f"Unsupported promotion target: {target}"
        )

    catalog_path = (
        root / "catalog.json"
    )

    submissions_path = (
        root / "submissions"
    )

    catalog = _load_json(
        catalog_path
    )

    existing = _catalog_mapping(
        catalog,
        mapping_id,
    )

    # -----------------------------------------------------
    # experimental -> community
    # -----------------------------------------------------
    if target == "community":
        if existing is not None:
            current = existing.get(
                "confidence"
            )

            raise ValueError(
                f"Mapping {mapping_id} is already "
                f"in catalog.json as {current!r}"
            )

        submission_path = (
            submissions_path
            / f"{mapping_id}.json"
        )

        if not submission_path.is_file():
            raise ValueError(
                f"Experimental submission not found: "
                f"{submission_path}"
            )

        submission = _load_json(
            submission_path
        )

        mappings = submission.get(
            "mappings"
        )

        if (
            not isinstance(
                mappings,
                list,
            )
            or len(mappings) != 1
            or not isinstance(
                mappings[0],
                dict,
            )
        ):
            raise ValueError(
                "Submission must contain exactly "
                "one mapping"
            )

        mapping = mappings[0]

        if (
            mapping.get("id")
            != mapping_id
        ):
            raise ValueError(
                "Submission mapping ID does not "
                "match its filename"
            )

        if (
            mapping.get("confidence")
            != "experimental"
        ):
            raise ValueError(
                "Only experimental submissions "
                "can be promoted to community"
            )

        promoted = copy.deepcopy(
            mapping
        )

        promoted[
            "confidence"
        ] = "community"

        catalog_mappings = (
            catalog.setdefault(
                "mappings",
                [],
            )
        )

        catalog_mappings.append(
            promoted
        )

        catalog_mappings.sort(
            key=lambda item: str(
                item.get(
                    "id",
                    "",
                )
            )
        )

        _save_json(
            catalog_path,
            catalog,
        )

        # Accepted submissions leave the inbox.
        submission_path.unlink()

        return (
            "experimental",
            "community",
        )

    # -----------------------------------------------------
    # community -> verified
    # -----------------------------------------------------
    if existing is None:
        submission_path = (
            submissions_path
            / f"{mapping_id}.json"
        )

        if submission_path.is_file():
            raise ValueError(
                "Mapping is still experimental. "
                "Promote it to community first."
            )

        raise ValueError(
            f"Mapping {mapping_id} was not found "
            "in catalog.json"
        )

    current = existing.get(
        "confidence"
    )

    if current != "community":
        raise ValueError(
            "Only community mappings can be "
            "promoted to verified; "
            f"current state is {current!r}"
        )

    existing[
        "confidence"
    ] = "verified"

    _save_json(
        catalog_path,
        catalog,
    )

    return (
        "community",
        "verified",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Promote a LocalTuya device mapping"
        )
    )

    parser.add_argument(
        "--mapping-id",
        required=True,
    )

    parser.add_argument(
        "--target",
        required=True,
        choices=sorted(TARGETS),
    )

    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
    )

    args = parser.parse_args()

    try:
        old_state, new_state = (
            promote_mapping(
                args.root.resolve(),
                args.mapping_id,
                args.target,
            )
        )
    except ValueError as exc:
        parser.error(
            str(exc)
        )

    print(
        f"Promoted {args.mapping_id}: "
        f"{old_state} -> {new_state}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
