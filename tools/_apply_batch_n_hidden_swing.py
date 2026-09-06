from pathlib import Path

p = Path("tools/import_tuya_local_productless.py")
text = p.read_text(encoding="utf-8")

old = '''    has_advanced = False\n    for raw_dp in raw_dps:\n        if not isinstance(raw_dp, dict):\n            continue\n        for rule in _raw_mapping(raw_dp):\n            if set(rule) & (_ADVANCED_SOURCE_KEYS | _UNSUPPORTED_ADVANCED_KEYS):\n                has_advanced = True\n                break\n        if has_advanced:\n            break\n'''
new = '''    def needs_advanced(name: Any, rule: dict[str, Any]) -> bool:\n        if set(rule) & (_ADVANCED_SOURCE_KEYS | _UNSUPPORTED_ADVANCED_KEYS):\n            return True\n        # Tuya Local hidden mappings still participate in forward/read mapping\n        # but are excluded from value lists and reverse writes. LocalTuya's\n        # advanced mapper has the same semantics. Batch N enables this only for\n        # Climate swing enums where hidden rules are forward-only fallbacks.\n        return (\n            platform == "climate"\n            and name in {"swing_mode", "swing_horizontal_mode"}\n            and rule.get("hidden") is True\n        )\n\n    has_advanced = False\n    for raw_dp in raw_dps:\n        if not isinstance(raw_dp, dict):\n            continue\n        name = raw_dp.get("name")\n        for rule in _raw_mapping(raw_dp):\n            if needs_advanced(name, rule):\n                has_advanced = True\n                break\n        if has_advanced:\n            break\n'''
if new not in text:
    if old not in text:
        raise SystemExit("first advanced trigger anchor missing")
    text = text.replace(old, new, 1)

old2 = '''        if not any(\n            set(rule) & (_ADVANCED_SOURCE_KEYS | _UNSUPPORTED_ADVANCED_KEYS)\n            for rule in rules\n        ):\n            continue\n'''
new2 = '''        if not any(needs_advanced(name, rule) for rule in rules):\n            continue\n'''
if new2 not in text:
    if old2 not in text:
        raise SystemExit("second advanced trigger anchor missing")
    text = text.replace(old2, new2, 1)

p.write_text(text, encoding="utf-8")

t = Path("tests/test_productless_climate_hidden_swing.py")
if not t.exists():
    t.write_text('''"""Batch N hidden Climate swing forward-fallback tests."""\n\nimport unittest\n\nimport import_tuya_local_productless as productless\n\n\nclass ProductlessClimateHiddenSwingTests(unittest.TestCase):\n    def test_hidden_swing_default_becomes_forward_only_advanced_mapping(self):\n        entity = {\n            "entity": "climate",\n            "dps": [\n                {\n                    "id": 1, "name": "hvac_mode", "type": "boolean",\n                    "mapping": [\n                        {"dps_val": False, "value": "off"},\n                        {"dps_val": True, "value": "heat"},\n                    ],\n                },\n                {\n                    "id": 113, "name": "swing_mode", "type": "string",\n                    "mapping": [\n                        {"dps_val": "0", "value": "off"},\n                        {"dps_val": "1", "value": "on"},\n                        {"value": "on", "hidden": True},\n                    ],\n                },\n            ],\n        }\n        prepared, advanced, membership = productless._prepare_advanced_entity(entity, "climate")\n        self.assertIn("113", advanced)\n        self.assertEqual(advanced["113"][-1], {"value": "on", "hidden": True})\n        swing = next(dp for dp in prepared["dps"] if dp["name"] == "swing_mode")\n        self.assertEqual(\n            swing["mapping"],\n            [{"dps_val": "off", "value": "off"}, {"dps_val": "on", "value": "on"}],\n        )\n        self.assertIn(113, membership)\n\n    def test_hidden_preset_is_not_broadened_by_swing_tranche(self):\n        entity = {\n            "entity": "climate",\n            "dps": [{\n                "id": 5, "name": "preset_mode", "type": "string",\n                "mapping": [\n                    {"dps_val": "low", "value": "none", "hidden": True},\n                    {"dps_val": "high", "value": "boost"},\n                ],\n            }],\n        }\n        prepared, advanced, membership = productless._prepare_advanced_entity(entity, "climate")\n        self.assertEqual(advanced, {})\n        self.assertEqual(membership, set())\n        self.assertEqual(prepared, entity)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''', encoding="utf-8")
