"""Regression test for Tuya Local duration-class time entities."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from import_tuya_local_productless import convert_profile  # noqa: E402


class ProductlessDurationTimeTests(unittest.TestCase):
    def test_duration_class_second_timer_is_lossless(self):
        result = convert_profile(
            {
                "name": "Timer",
                "products": [{"id": "synthetic"}],
                "entities": [{
                    "entity": "time", "class": "duration", "category": "config",
                    "dps": [{"id": 26, "name": "second", "type": "integer", "optional": True, "range": {"min": 0, "max": 86400}}],
                }, {"entity": "switch", "dps": [{"id": 20, "name": "switch", "type": "boolean"}]}],
            },
            source_file="timer.yaml",
        )
        time_config = next(entity["config"] for entity in result["entities"] if entity["platform"] == "time")
        self.assertEqual(time_config["time_second_dp"], 26)
        self.assertIn(26, result["match"]["optional_dps"])


if __name__ == "__main__":
    unittest.main()
