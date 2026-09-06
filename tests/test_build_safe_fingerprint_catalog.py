"""Tests for fail-closed productless fingerprint publication filtering."""

from __future__ import annotations

import unittest

from tools.build_safe_fingerprint_catalog import build_catalog, classify_fingerprints


def fp(mapping_id, required, optional=None):
    return {
        "id": mapping_id,
        "confidence": "experimental",
        "match": {
            "product_ids": [],
            "category": None,
            "required_dps": required,
            "optional_dps": optional or [],
            "fingerprint": {"mode": "exact_dps"},
        },
        "entities": [
            {
                "platform": "switch",
                "config": {"id": required[0], "platform": "switch"},
            }
        ],
        "provenance": {
            "source": "make-all/tuya-local",
            "path": f"custom_components/tuya_local/devices/{mapping_id}.yaml",
            "license": "MIT",
        },
    }


class SafeFingerprintBuilderTests(unittest.TestCase):
    def test_disjoint_exact_fingerprints_are_safe(self):
        safe, blocked = classify_fingerprints([
            fp("one", [1]),
            fp("two", [1, 2]),
        ])
        self.assertEqual([item["id"] for item in safe], ["one", "two"])
        self.assertEqual(blocked, [])

    def test_exact_duplicate_fingerprints_are_blocked(self):
        safe, blocked = classify_fingerprints([
            fp("one", [1, 2]),
            fp("two", [1, 2]),
        ])
        self.assertEqual(safe, [])
        self.assertEqual({item.mapping_id for item in blocked}, {"one", "two"})
        self.assertTrue(all(item.reason == "ambiguous" for item in blocked))

    def test_optional_dp_variant_that_ties_is_blocked(self):
        safe, blocked = classify_fingerprints([
            fp("base", [1]),
            fp("variant", [1], [2]),
        ])
        self.assertEqual(safe, [])
        self.assertEqual({item.mapping_id for item in blocked}, {"base", "variant"})

    def test_shadowed_candidate_is_blocked(self):
        safe, blocked = classify_fingerprints([
            fp("weak", [1], [2]),
            fp("strong", [1, 2]),
        ])
        self.assertEqual([item["id"] for item in safe], ["strong"])
        weak = next(item for item in blocked if item.mapping_id == "weak")
        self.assertEqual(weak.reason, "shadowed")

    def test_duplicate_platform_primary_dp_is_blocked_before_scoring(self):
        bad = fp("bad", [1, 2])
        bad["entities"].append(
            {"platform": "switch", "config": {"id": 1, "platform": "switch"}}
        )
        safe, blocked = classify_fingerprints([bad, fp("good", [3])])
        self.assertEqual([item["id"] for item in safe], ["good"])
        failure = next(item for item in blocked if item.mapping_id == "bad")
        self.assertEqual(failure.reason, "duplicate_entity_primary_dp")

    def test_build_replaces_previous_imported_productless_entries(self):
        existing_old = fp("old", [9])
        existing = {
            "schema_version": 3,
            "mappings": [
                {
                    "id": "real-product",
                    "confidence": "verified",
                    "match": {
                        "product_ids": ["abc"],
                        "category": None,
                        "required_dps": [1],
                        "optional_dps": [],
                    },
                    "entities": [
                        {
                            "platform": "switch",
                            "config": {"id": 1, "platform": "switch"},
                        }
                    ],
                },
                existing_old,
            ],
        }
        catalog, report = build_catalog(existing, [fp("new", [2])])
        ids = [mapping["id"] for mapping in catalog["mappings"]]
        self.assertEqual(ids, ["real-product", "new"])
        self.assertEqual(catalog["schema_version"], 3)
        self.assertEqual(report["safe_candidates"], 1)


if __name__ == "__main__":
    unittest.main()
