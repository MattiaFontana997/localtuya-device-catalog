"""Tests for LocalTuya catalog schema v2 semantics."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.validate_catalog import load_json, validate_document


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = load_json(ROOT / "schema" / "catalog.schema.json")


def document(*, required=None, optional=None, config=None, products=None):
    required = [1] if required is None else required
    optional = [] if optional is None else optional
    config = {"id": 1, "platform": "switch"} if config is None else config
    products = ["product-a"] if products is None else products
    return {
        "schema_version": 2,
        "mappings": [
            {
                "id": "product-a-test",
                "confidence": "experimental",
                "match": {
                    "product_ids": products,
                    "category": "kg",
                    "required_dps": required,
                    "optional_dps": optional,
                },
                "entities": [
                    {
                        "platform": "switch",
                        "config": config,
                    }
                ],
                "provenance": {
                    "source": "make-all/tuya-local",
                    "path": "custom_components/tuya_local/devices/example.yaml",
                    "revision": "deadbeef",
                    "license": "MIT",
                },
            }
        ],
        "fingerprint": {
            "observed_dps": sorted(set(required) | set(optional)),
            "required_dps": required,
            "optional_dps": optional,
            "protocol_version": "3.5",
            "entity_count": 1,
        },
    }


class CatalogV2ValidationTests(unittest.TestCase):
    def validate(self, payload: dict) -> list[str]:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            submissions = root / "submissions"
            submissions.mkdir()
            path = submissions / "product-a-test.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return validate_document(path, SCHEMA)

    def test_multiple_product_ids_optional_dps_and_provenance_are_valid(self):
        payload = document(
            required=[1],
            optional=[18],
            products=["alias-a", "product-a"],
            config={
                "id": 1,
                "platform": "switch",
                "current_consumption": 18,
            },
        )
        # Canonical submission ids are content-derived. This test targets schema
        # and semantic structure, so use catalog.json to avoid the filename/id
        # canonicality rule.
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "catalog.json"
            payload.pop("fingerprint")
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(validate_document(path, SCHEMA), [])

    def test_required_and_optional_dps_cannot_overlap(self):
        payload = document(required=[1, 18], optional=[18])
        errors = self.validate(payload)
        self.assertTrue(any("both required and optional" in error for error in errors))

    def test_referenced_dp_must_be_declared_required_or_optional(self):
        payload = document(
            required=[1],
            optional=[],
            config={
                "id": 1,
                "platform": "switch",
                "current_consumption": 18,
            },
        )
        errors = self.validate(payload)
        self.assertTrue(
            any("missing from required_dps/optional_dps" in error for error in errors)
        )

    def test_product_ids_are_deterministically_sorted(self):
        payload = document(products=["product-a", "alias-a"])
        errors = self.validate(payload)
        self.assertTrue(any("product_ids must be sorted" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
