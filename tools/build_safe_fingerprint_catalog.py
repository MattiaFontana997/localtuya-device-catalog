"""Build a Catalog V3 snapshot from unambiguous productless fingerprints.

The builder consumes mappings emitted by import_tuya_local_fingerprints.py and
mirrors LocalTuya's exact-DPS fingerprint ranking. A candidate is publishable
only when it is structurally usable and the unique best match for every device
state allowed by its own required/optional DPS declaration. Candidates that
tie, lose, or would create duplicate HA entities fail closed and are omitted.
"""

from __future__ import annotations

import argparse
import itertools
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

SOURCE_REPOSITORY = "make-all/tuya-local"
FINGERPRINT_MODE = {"mode": "exact_dps"}


@dataclass(frozen=True, slots=True)
class BlockedFingerprint:
    """One fingerprint excluded from automatic catalog publication."""

    mapping_id: str
    available_dps: tuple[int, ...]
    best_matches: tuple[str, ...]
    reason: str


def _load_mapping_files(directory: Path) -> list[dict[str, Any]]:
    mappings: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for mapping in payload.get("mappings", []):
            mapping_id = mapping.get("id")
            if not isinstance(mapping_id, str) or mapping_id in seen_ids:
                raise ValueError(f"duplicate or invalid mapping id in {path}: {mapping_id!r}")
            match = mapping.get("match", {})
            if match.get("product_ids") != [] or match.get("fingerprint") != FINGERPRINT_MODE:
                raise ValueError(f"{path}: not an exact productless fingerprint mapping")
            if mapping.get("confidence") == "verified":
                raise ValueError(f"{path}: productless fingerprint cannot be verified")
            seen_ids.add(mapping_id)
            mappings.append(mapping)
    return mappings


def _compatible_score(mapping: dict[str, Any], available_dps: set[int]) -> int | None:
    """Mirror LocalTuya's productless exact-DPS score."""
    match = mapping["match"]
    required = set(match.get("required_dps", []))
    optional = set(match.get("optional_dps", []))
    declared = required | optional
    if not required.issubset(available_dps) or available_dps - declared:
        return None
    return len(required) * 4 + len(optional & available_dps)


def _allowed_states(mapping: dict[str, Any]) -> Iterable[set[int]]:
    match = mapping["match"]
    required = set(match.get("required_dps", []))
    optional = sorted(set(match.get("optional_dps", [])))
    # Keep combinatorial analysis explicitly bounded for untrusted generated data.
    if len(optional) > 16:
        raise ValueError(f"{mapping['id']}: too many optional DPS to analyze safely")
    for mask in itertools.product((False, True), repeat=len(optional)):
        yield required | {dp for dp, present in zip(optional, mask) if present}


def _structural_failure(mapping: dict[str, Any]) -> BlockedFingerprint | None:
    """Reject entity layouts that cannot have stable HA identities."""
    seen_entities: set[tuple[str, int]] = set()
    for entity in mapping.get("entities", []):
        try:
            key = (str(entity["platform"]), int(entity["config"]["id"]))
        except (KeyError, TypeError, ValueError):
            return BlockedFingerprint(mapping["id"], (), (), "invalid_entity")
        if key in seen_entities:
            return BlockedFingerprint(
                mapping["id"],
                tuple(mapping["match"].get("required_dps", [])),
                (),
                "duplicate_entity_primary_dp",
            )
        seen_entities.add(key)
    return None


def classify_fingerprints(
    mappings: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[BlockedFingerprint]]:
    """Return candidates that remain structurally valid and uniquely identifiable."""
    safe: list[dict[str, Any]] = []
    blocked: list[BlockedFingerprint] = []
    eligible: list[dict[str, Any]] = []

    # Invalid candidates must not participate in ambiguity scoring: they will
    # never be published and therefore cannot legitimately shadow a valid one.
    for mapping in mappings:
        failure = _structural_failure(mapping)
        if failure is None:
            eligible.append(mapping)
        else:
            blocked.append(failure)

    for candidate in eligible:
        candidate_id = candidate["id"]
        failure: BlockedFingerprint | None = None
        for available in _allowed_states(candidate):
            scored = [
                (score, mapping["id"])
                for mapping in eligible
                if (score := _compatible_score(mapping, available)) is not None
            ]
            if not scored:
                failure = BlockedFingerprint(
                    candidate_id,
                    tuple(sorted(available)),
                    (),
                    "no_match",
                )
                break
            best_score = max(score for score, _ in scored)
            best = tuple(sorted(mapping_id for score, mapping_id in scored if score == best_score))
            if best != (candidate_id,):
                failure = BlockedFingerprint(
                    candidate_id,
                    tuple(sorted(available)),
                    best,
                    "ambiguous" if candidate_id in best else "shadowed",
                )
                break
        if failure is None:
            safe.append(candidate)
        else:
            blocked.append(failure)

    return safe, blocked


def build_catalog(
    existing: dict[str, Any],
    generated: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Replace imported productless fingerprints with the current safe set."""
    safe, blocked = classify_fingerprints(generated)

    preserved: list[dict[str, Any]] = []
    for mapping in existing.get("mappings", []):
        match = mapping.get("match", {})
        provenance = mapping.get("provenance", {})
        is_imported_productless = (
            match.get("product_ids") == []
            and match.get("fingerprint") == FINGERPRINT_MODE
            and provenance.get("source") == SOURCE_REPOSITORY
        )
        if not is_imported_productless:
            preserved.append(mapping)

    safe = sorted(safe, key=lambda mapping: mapping["id"])
    blocked = sorted(blocked, key=lambda item: item.mapping_id)
    result = {
        "schema_version": 3,
        "mappings": preserved + safe,
    }
    report = {
        "generated_candidates": len(generated),
        "safe_candidates": len(safe),
        "blocked_candidates": len(blocked),
        "published_mapping_ids": [mapping["id"] for mapping in safe],
        "blocked": [asdict(item) for item in blocked],
    }
    return result, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a fail-closed Catalog V3 fingerprint snapshot.")
    parser.add_argument("--catalog", type=Path, default=Path("catalog.json"))
    parser.add_argument("--generated-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    existing = json.loads(args.catalog.read_text(encoding="utf-8"))
    generated = _load_mapping_files(args.generated_dir)
    catalog, report = build_catalog(existing, generated)
    args.output.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Generated candidates: {report['generated_candidates']}")
    print(f"Safe candidates: {report['safe_candidates']}")
    print(f"Blocked candidates: {report['blocked_candidates']}")
    for item in report["blocked"]:
        print(
            f"BLOCKED {item['mapping_id']} state={item['available_dps']} "
            f"reason={item['reason']} best={item['best_matches']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
