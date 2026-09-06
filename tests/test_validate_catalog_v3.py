"""Regression tests for Catalog V3 productless fingerprint semantics."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.validate_catalog import load_json, validate_document


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = load_json(ROOT / "schema" / "catalog.schema.json")


def mapping(*, products=None, fingerprint=True, confidence="experimental", platform="switch"):
    products = [] if products is None else products
    match = {
        "product_ids": products,
        "category": None,
        "required_dps": [1],
        "optional_dps": [],
    }
    if fingerprint:
        match["fingerprint"] = {"mode": "exact_dps"}
    return {
        "id": "fingerprint-test-device-0123456789",
        "confidence": confidence,
        "match": match,
        "entities": [
            {
                "platform": platform,
                "config": {"id": 1, "platform": platform},
            }
        ],
        "provenance": {
            "source": "make-all/tuya-local",
            "path": "custom_components/tuya_local/devices/example.yaml",
            "revision": "deadbeef",
            "license": "MIT",
        },
    }


def validate_catalog_payload(payload: dict) -> list[str]:
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "catalog.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return validate_document(path, SCHEMA)


class CatalogV3ValidationTests(unittest.TestCase):
    def test_v3_productless_exact_dps_fingerprint_is_valid(self):
        payload = {"schema_version": 3, "mappings": [mapping()]}
        self.assertEqual(validate_catalog_payload(payload), [])

    def test_v2_cannot_contain_productless_fingerprint(self):
        payload = {"schema_version": 2, "mappings": [mapping()]}
        self.assertTrue(validate_catalog_payload(payload))

    def test_v3_product_mapping_remains_valid(self):
        item = mapping(products=["product-a"], fingerprint=False)
        item["id"] = "product-a-test"
        payload = {"schema_version": 3, "mappings": [item]}
        self.assertEqual(validate_catalog_payload(payload), [])

    def test_productless_mapping_without_fingerprint_is_rejected(self):
        payload = {
            "schema_version": 3,
            "mappings": [mapping(fingerprint=False)],
        }
        self.assertTrue(validate_catalog_payload(payload))

    def test_product_id_and_fingerprint_cannot_be_combined(self):
        payload = {
            "schema_version": 3,
            "mappings": [mapping(products=["product-a"], fingerprint=True)],
        }
        self.assertTrue(validate_catalog_payload(payload))

    def test_productless_fingerprint_cannot_be_verified(self):
        payload = {
            "schema_version": 3,
            "mappings": [mapping(confidence="verified")],
        }
        self.assertTrue(validate_catalog_payload(payload))

    def test_fingerprint_mode_is_exact_dps_only(self):
        item = mapping()
        item["match"]["fingerprint"] = {"mode": "heuristic"}
        payload = {"schema_version": 3, "mappings": [item]}
        self.assertTrue(validate_catalog_payload(payload))

    def test_batch_bc_platforms_are_schema_valid(self):
        item = mapping(platform="time")
        payload = {"schema_version": 3, "mappings": [item]}
        self.assertEqual(validate_catalog_payload(payload), [])


if __name__ == "__main__":
    unittest.main()
