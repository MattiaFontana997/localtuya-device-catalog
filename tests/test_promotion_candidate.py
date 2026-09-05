"""Tests for duplicate promotion candidate checks."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.check_promotion_candidate import ensure_no_catalog_selector_duplicate


def make_mapping(
    mapping_id: str,
    confidence: str,
    *,
    product_ids: list[str] | None = None,
    category: str = "wk",
    required_dps: list[int] | None = None,
    optional_dps: list[int] | None = None,
) -> dict:
    return {
        "id": mapping_id,
        "confidence": confidence,
        "match": {
            "product_ids": product_ids or ["product123"],
            "category": category,
            "required_dps": required_dps or [1],
            "optional_dps": optional_dps or [],
        },
        "entities": [
            {
                "platform": "switch",
                "config": {
                    "id": 1,
                    "platform": "switch",
                },
            }
        ],
    }


class PromotionCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "submissions").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def write_catalog(self, mappings: list[dict]) -> None:
        (self.root / "catalog.json").write_text(
            json.dumps({"schema_version": 2, "mappings": mappings}),
            encoding="utf-8",
        )

    def write_submission(self, mapping: dict) -> None:
        mapping_id = mapping["id"]
        match = mapping["match"]
        observed = sorted(set(match["required_dps"]) | set(match["optional_dps"]))
        (self.root / "submissions" / f"{mapping_id}.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "mappings": [mapping],
                    "fingerprint": {
                        "observed_dps": observed,
                        "required_dps": match["required_dps"],
                        "optional_dps": match["optional_dps"],
                        "protocol_version": "3.3",
                        "entity_count": 1,
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_duplicate_selector_is_rejected(self):
        existing = make_mapping(
            "product123-existing",
            "verified",
            product_ids=["alias123", "product123"],
            required_dps=[1, 2, 16],
            optional_dps=[18],
        )
        candidate = make_mapping(
            "product123-candidate",
            "experimental",
            product_ids=["product123", "alias123"],
            required_dps=[16, 2, 1],
            optional_dps=[18],
        )

        self.write_catalog([existing])
        self.write_submission(candidate)

        with self.assertRaisesRegex(
            ValueError,
            "same product_ids/category/required_dps/optional_dps selector",
        ):
            ensure_no_catalog_selector_duplicate(self.root, candidate["id"])

    def test_different_required_dps_is_allowed(self):
        existing = make_mapping(
            "product123-existing",
            "verified",
            required_dps=[1, 2],
        )
        candidate = make_mapping(
            "product123-candidate",
            "experimental",
            required_dps=[1, 2, 16],
        )

        self.write_catalog([existing])
        self.write_submission(candidate)
        ensure_no_catalog_selector_duplicate(self.root, candidate["id"])

    def test_different_optional_dps_is_allowed(self):
        existing = make_mapping(
            "product123-existing",
            "verified",
            optional_dps=[18],
        )
        candidate = make_mapping(
            "product123-candidate",
            "experimental",
            optional_dps=[19],
        )

        self.write_catalog([existing])
        self.write_submission(candidate)
        ensure_no_catalog_selector_duplicate(self.root, candidate["id"])

    def test_different_product_set_is_allowed(self):
        existing = make_mapping(
            "product123-existing",
            "verified",
        )
        candidate = make_mapping(
            "product456-candidate",
            "experimental",
            product_ids=["product456"],
        )

        self.write_catalog([existing])
        self.write_submission(candidate)
        ensure_no_catalog_selector_duplicate(self.root, candidate["id"])


if __name__ == "__main__":
    unittest.main()
