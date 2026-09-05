"""Tests for safe productless Tuya Local fingerprint conversion."""

import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from import_tuya_local import ConversionError  # noqa: E402
from import_tuya_local_fingerprints import convert_productless_profile  # noqa: E402


class FingerprintImporterTests(unittest.TestCase):
    def test_simple_productless_switch_converts(self):
        profile = {
            "name": "Generic switch profile",
            "entities": [{
                "entity": "switch",
                "dps": [{"id": 1, "type": "boolean", "name": "switch"}],
            }],
        }
        mapping = convert_productless_profile(
            profile, source_file="generic_switch.yaml", revision="abc123"
        )
        self.assertEqual(mapping["confidence"], "experimental")
        self.assertEqual(mapping["match"]["product_ids"], [])
        self.assertEqual(mapping["match"]["required_dps"], [1])
        self.assertEqual(mapping["match"]["fingerprint"], {"mode": "exact_dps"})
        self.assertTrue(mapping["id"].startswith("fingerprint-generic_switch-"))
        self.assertEqual(mapping["provenance"]["source"], "make-all/tuya-local")

    def test_existing_product_id_is_rejected(self):
        profile = {
            "name": "Known product",
            "products": [{"id": "abcdefgh12345678"}],
            "entities": [{
                "entity": "switch",
                "dps": [{"id": 1, "type": "boolean", "name": "switch"}],
            }],
        }
        with self.assertRaisesRegex(ConversionError, "has_product_id"):
            convert_productless_profile(profile, source_file="known.yaml")

    def test_converter_still_fails_closed_on_unsupported_semantics(self):
        profile = {
            "name": "Unsafe switch",
            "entities": [{
                "entity": "switch",
                "dps": [{
                    "id": 1,
                    "type": "boolean",
                    "name": "switch",
                    "sensitive": True,
                }],
            }],
        }
        with self.assertRaises(ConversionError):
            convert_productless_profile(profile, source_file="unsafe.yaml")


if __name__ == "__main__":
    unittest.main()
