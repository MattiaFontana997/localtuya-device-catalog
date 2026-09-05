"""Tests for trusted mapping promotion."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.promote_mapping import promote_mapping


def mapping(mapping_id: str, confidence: str):
    return {
        "id": mapping_id,
        "confidence": confidence,
        "match": {
            "product_ids": ["product123"],
            "category": "wk",
            "required_dps": [1],
            "optional_dps": [],
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


class PromoteMappingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "submissions").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def write_catalog(self, mappings):
        (self.root / "catalog.json").write_text(
            json.dumps({"schema_version": 2, "mappings": mappings}),
            encoding="utf-8",
        )

    def write_submission(self, mapping_id: str, confidence: str) -> Path:
        submission_path = self.root / "submissions" / f"{mapping_id}.json"
        submission_path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "mappings": [mapping(mapping_id, confidence)],
                    "fingerprint": {
                        "observed_dps": [1],
                        "required_dps": [1],
                        "optional_dps": [],
                        "protocol_version": "3.3",
                        "entity_count": 1,
                    },
                }
            ),
            encoding="utf-8",
        )
        return submission_path

    def test_experimental_promotes_to_community(self):
        mapping_id = "product123-aabbccddee"
        self.write_catalog([])
        submission_path = self.write_submission(mapping_id, "experimental")

        result = promote_mapping(self.root, mapping_id, "community")

        self.assertEqual(result, ("experimental", "community"))
        self.assertFalse(submission_path.exists())

        catalog = json.loads(
            (self.root / "catalog.json").read_text(encoding="utf-8")
        )
        self.assertEqual(catalog["schema_version"], 2)
        self.assertEqual(catalog["mappings"][0]["confidence"], "community")
        self.assertEqual(
            catalog["mappings"][0]["match"]["product_ids"], ["product123"]
        )

    def test_community_promotes_to_verified(self):
        mapping_id = "product123-aabbccddee"
        self.write_catalog([mapping(mapping_id, "community")])

        result = promote_mapping(self.root, mapping_id, "verified")
        self.assertEqual(result, ("community", "verified"))

        catalog = json.loads(
            (self.root / "catalog.json").read_text(encoding="utf-8")
        )
        self.assertEqual(catalog["mappings"][0]["confidence"], "verified")

    def test_experimental_cannot_skip_community(self):
        mapping_id = "product123-aabbccddee"
        self.write_catalog([])
        self.write_submission(mapping_id, "experimental")

        with self.assertRaisesRegex(ValueError, "community first"):
            promote_mapping(self.root, mapping_id, "verified")

    def test_mapping_id_cannot_escape_submissions(self):
        self.write_catalog([])

        with self.assertRaisesRegex(ValueError, "Invalid mapping ID"):
            promote_mapping(self.root, "../catalog", "community")


if __name__ == "__main__":
    unittest.main()
