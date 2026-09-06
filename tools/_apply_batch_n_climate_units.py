from pathlib import Path

path = Path('tools/import_tuya_local_productless.py')
text = path.read_text(encoding='utf-8')

marker = '\n\ndef _prepare_advanced_entity('
insert = r'''


def _normalize_climate_temperature_unit(entity: dict[str, Any]) -> dict[str, Any]:
    """Normalize explicit Tuya Local C/F friendly values for LocalTuya Climate.

    Tuya Local device YAML commonly exposes friendly ``C``/``F`` while the
    LocalTuya runtime's catalog contract uses ``celsius``/``fahrenheit``. Raw
    device values remain untouched. Forward/default rules without an exact raw
    value are deliberately left fail-closed because they cannot define a
    reversible raw unit map.
    """
    if entity.get("entity") != "climate":
        return entity
    dps = entity.get("dps")
    if not isinstance(dps, list):
        return entity
    unit = next(
        (
            dp for dp in dps
            if isinstance(dp, dict) and dp.get("name") == "temperature_unit"
        ),
        None,
    )
    if unit is None:
        return entity
    rules = _raw_mapping(unit)
    if not rules:
        return entity

    normalized = copy.deepcopy(entity)
    normalized_unit = next(
        dp for dp in normalized["dps"]
        if isinstance(dp, dict) and dp.get("name") == "temperature_unit"
    )
    normalized_rules = _raw_mapping(normalized_unit)
    seen_units: set[str] = set()
    seen_raw: list[Any] = []
    aliases = {
        "C": "celsius",
        "°C": "celsius",
        "celsius": "celsius",
        "F": "fahrenheit",
        "°F": "fahrenheit",
        "fahrenheit": "fahrenheit",
    }
    for rule in normalized_rules:
        if set(rule) - {"dps_val", "value", "hidden"}:
            raise ConversionError("climate_temperature_unit_mapping")
        if rule.get("hidden") is True or "dps_val" not in rule or "value" not in rule:
            raise ConversionError("climate_temperature_unit_mapping")
        friendly = rule["value"]
        if not isinstance(friendly, str) or friendly not in aliases:
            raise ConversionError("climate_temperature_unit_friendly")
        friendly = aliases[friendly]
        raw = rule["dps_val"]
        if friendly in seen_units or any(raw == previous and type(raw) is type(previous) for previous in seen_raw):
            raise ConversionError("climate_temperature_unit_duplicate")
        seen_units.add(friendly)
        seen_raw.append(raw)
        rule["value"] = friendly
    if seen_units != {"celsius", "fahrenheit"}:
        raise ConversionError("climate_temperature_unit_mapping")
    return normalized
'''
if marker not in text:
    raise SystemExit('prepare marker missing')
text = text.replace(marker, insert + marker, 1)

old = '''        flagged, disabled_default, hidden_extra_names, non_persistent_dps = (\n            _prepare_runtime_flags(entity, platform)\n        )\n        prepared, advanced_by_dp, membership_ids = _prepare_advanced_entity(\n            flagged, platform\n        )'''
new = '''        flagged, disabled_default, hidden_extra_names, non_persistent_dps = (\n            _prepare_runtime_flags(entity, platform)\n        )\n        if platform == "climate":\n            flagged = _normalize_climate_temperature_unit(flagged)\n        prepared, advanced_by_dp, membership_ids = _prepare_advanced_entity(\n            flagged, platform\n        )'''
if old not in text:
    raise SystemExit('wrapper marker missing')
text = text.replace(old, new, 1)

path.write_text(text, encoding='utf-8')

test = Path('tests/test_productless_climate_units.py')
test.write_text('''"""Batch N exact Climate temperature-unit normalization tests."""\n\nimport unittest\n\nimport import_tuya_local_productless as productless\n\n\nclass ProductlessClimateUnitTests(unittest.TestCase):\n    def test_string_raw_units_preserve_raw_values(self):\n        entity = {\n            "entity": "climate",\n            "dps": [{\n                "id": 19, "name": "temperature_unit", "type": "string",\n                "mapping": [\n                    {"dps_val": "c", "value": "C"},\n                    {"dps_val": "f", "value": "F"},\n                ],\n            }],\n        }\n        normalized = productless._normalize_climate_temperature_unit(entity)\n        self.assertEqual(normalized["dps"][0]["mapping"], [\n            {"dps_val": "c", "value": "celsius"},\n            {"dps_val": "f", "value": "fahrenheit"},\n        ])\n        self.assertEqual(entity["dps"][0]["mapping"][0]["value"], "C")\n\n    def test_boolean_raw_units_remain_typed(self):\n        entity = {\n            "entity": "climate",\n            "dps": [{\n                "id": 107, "name": "temperature_unit", "type": "boolean",\n                "mapping": [\n                    {"dps_val": False, "value": "C"},\n                    {"dps_val": True, "value": "F"},\n                ],\n            }],\n        }\n        normalized = productless._normalize_climate_temperature_unit(entity)\n        rules = normalized["dps"][0]["mapping"]\n        self.assertIs(rules[0]["dps_val"], False)\n        self.assertIs(rules[1]["dps_val"], True)\n        self.assertEqual([r["value"] for r in rules], ["celsius", "fahrenheit"])
\n    def test_forward_only_unit_fallback_stays_fail_closed(self):\n        entity = {\n            "entity": "climate",\n            "dps": [{\n                "id": 23, "name": "temperature_unit", "type": "string",\n                "mapping": [\n                    {"dps_val": "f", "value": "F"},\n                    {"value": "C"},\n                ],\n            }],\n        }\n        with self.assertRaisesRegex(Exception, "climate_temperature_unit_mapping"):\n            productless._normalize_climate_temperature_unit(entity)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''', encoding='utf-8')
