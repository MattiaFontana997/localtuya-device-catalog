from pathlib import Path

path = Path("tools/import_tuya_local_productless.py")
text = path.read_text(encoding="utf-8")

helper = r'''

def _prepare_typed_productless_select(
    entity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    """Project finite boolean/integer selects onto string HA options losslessly.

    Home Assistant Select options are strings, while Tuya Local permits a
    boolean or integer raw DP with an explicit friendly string mapping. Keep the
    device-facing values typed in ``advanced_mapping_by_dp`` and give the mature
    LocalTuya select converter an identity string projection. Reads therefore
    map typed raw -> friendly string, and writes reverse-map that friendly string
    back to the exact typed raw value.
    """
    if entity.get("entity") != "select":
        return entity, {}
    dps = entity.get("dps")
    if not isinstance(dps, list):
        return entity, {}
    option = next(
        (dp for dp in dps if isinstance(dp, dict) and dp.get("name") == "option"),
        None,
    )
    if option is None:
        return entity, {}

    raw_type = base._dp_type(option)
    if raw_type == "string":
        return entity, {}
    if raw_type not in {"boolean", "integer"}:
        return entity, {}

    rules = _raw_mapping(option)
    if not rules or len(rules) > 64:
        raise ConversionError("select_non_string_mapping")

    runtime_rules: list[dict[str, Any]] = []
    identity_rules: list[dict[str, str]] = []
    seen_raw: list[Any] = []
    seen_friendly: set[str] = set()
    for rule in rules:
        if set(rule) != {"dps_val", "value"}:
            raise ConversionError("select_non_string_mapping")
        raw = rule.get("dps_val")
        friendly = rule.get("value")
        if raw_type == "boolean":
            if not isinstance(raw, bool):
                raise ConversionError("select_non_string_mapping")
        else:
            if isinstance(raw, bool) or not isinstance(raw, int):
                raise ConversionError("select_non_string_mapping")
        if (
            not isinstance(friendly, str)
            or not friendly
            or friendly != friendly.strip()
            or ";" in friendly
        ):
            raise ConversionError("select_non_string_mapping")
        if any(raw == previous and type(raw) is type(previous) for previous in seen_raw):
            raise ConversionError("select_duplicate_option")
        if friendly in seen_friendly:
            raise ConversionError("select_duplicate_option")
        seen_raw.append(raw)
        seen_friendly.add(friendly)
        runtime_rules.append({"dps_val": raw, "value": friendly})
        identity_rules.append({"dps_val": friendly, "value": friendly})

    transformed = copy.deepcopy(entity)
    transformed_option = next(
        dp for dp in transformed.get("dps", [])
        if isinstance(dp, dict) and dp.get("name") == "option"
    )
    transformed_option["type"] = "string"
    transformed_option["mapping"] = identity_rules
    return transformed, {str(base._dp_id(option)): runtime_rules}
'''

anchor = "\n\ndef _prepare_runtime_flags(\n"
if "def _prepare_typed_productless_select(" not in text:
    idx = text.find(anchor)
    if idx < 0:
        raise SystemExit("runtime flags anchor missing")
    text = text[:idx] + helper + text[idx:]

old = '''        climate_limit_precisions: dict[str, float] = {}\n        climate_dynamic_target_range = False\n        if platform == "climate":\n            flagged = _normalize_climate_temperature_unit(flagged)\n            flagged, climate_limit_precisions = _prepare_climate_limit_precisions(flagged)\n            flagged, climate_dynamic_target_range = _prepare_climate_dynamic_target_range(flagged)\n        prepared, advanced_by_dp, membership_ids = _prepare_advanced_entity(\n            flagged, platform\n        )\n'''
new = '''        climate_limit_precisions: dict[str, float] = {}\n        climate_dynamic_target_range = False\n        typed_select_mapping: dict[str, list[dict[str, Any]]] = {}\n        if platform == "climate":\n            flagged = _normalize_climate_temperature_unit(flagged)\n            flagged, climate_limit_precisions = _prepare_climate_limit_precisions(flagged)\n            flagged, climate_dynamic_target_range = _prepare_climate_dynamic_target_range(flagged)\n        elif platform == "select":\n            flagged, typed_select_mapping = _prepare_typed_productless_select(flagged)\n        prepared, advanced_by_dp, membership_ids = _prepare_advanced_entity(\n            flagged, platform\n        )\n        for dp_id, rules in typed_select_mapping.items():\n            existing = advanced_by_dp.get(dp_id)\n            if existing is not None and existing != rules:\n                raise ConversionError("select_advanced_mapping_conflict")\n            advanced_by_dp[dp_id] = copy.deepcopy(rules)\n'''
if new not in text:
    if old not in text:
        raise SystemExit("advanced wrapper select insertion anchor missing")
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")

# Permanent tests.
test_path = Path("tests/test_import_tuya_local_productless.py")
test = test_path.read_text(encoding="utf-8")
methods = r'''

    def test_integer_select_projects_friendly_options_and_keeps_typed_raw_mapping(self):
        result = self._convert([
            {
                "entity": "select",
                "dps": [{
                    "id": 102,
                    "name": "option",
                    "type": "integer",
                    "mapping": [
                        {"dps_val": 0, "value": "Internal"},
                        {"dps_val": 1, "value": "External"},
                        {"dps_val": 2, "value": "Both"},
                    ],
                }],
            }
        ])
        config = result["entities"][0]["config"]
        self.assertEqual(config["options"], "Internal;External;Both")
        self.assertNotIn("options_friendly", config)
        self.assertEqual(config["advanced_mapping_by_dp"]["102"], [
            {"dps_val": 0, "value": "Internal"},
            {"dps_val": 1, "value": "External"},
            {"dps_val": 2, "value": "Both"},
        ])
        self.assertEqual(result["match"]["required_dps"], [102])

    def test_boolean_select_preserves_boolean_raw_values(self):
        result = self._convert([
            {
                "entity": "select",
                "translation_key": "temperature_unit",
                "dps": [{
                    "id": 10,
                    "name": "option",
                    "type": "boolean",
                    "mapping": [
                        {"dps_val": True, "value": "fahrenheit"},
                        {"dps_val": False, "value": "celsius"},
                    ],
                }],
            }
        ])
        config = result["entities"][0]["config"]
        self.assertEqual(config["options"], "fahrenheit;celsius")
        self.assertIs(config["advanced_mapping_by_dp"]["10"][0]["dps_val"], True)
        self.assertIs(config["advanced_mapping_by_dp"]["10"][1]["dps_val"], False)

    def test_large_integer_select_with_negative_raw_is_bounded_and_lossless(self):
        mapping = [
            {"dps_val": value, "value": f"Plant {value}"}
            for value in range(-1, 59)
        ]
        result = self._convert([
            {
                "entity": "select",
                "dps": [{
                    "id": 105,
                    "name": "option",
                    "type": "integer",
                    "mapping": mapping,
                }],
            }
        ])
        config = result["entities"][0]["config"]
        self.assertEqual(len(config["options"].split(";")), 60)
        self.assertEqual(config["advanced_mapping_by_dp"]["105"][0]["dps_val"], -1)
        self.assertEqual(config["advanced_mapping_by_dp"]["105"][-1]["dps_val"], 58)

    def test_typed_select_rejects_non_exact_or_oversized_mapping(self):
        with self.assertRaisesRegex(ConversionError, "select_non_string_mapping"):
            self._convert([
                {
                    "entity": "select",
                    "dps": [{
                        "id": 1,
                        "name": "option",
                        "type": "integer",
                        "mapping": [{"dps_val": 0, "value": "Zero", "hidden": True}],
                    }],
                }
            ])
        with self.assertRaisesRegex(ConversionError, "select_non_string_mapping"):
            self._convert([
                {
                    "entity": "select",
                    "dps": [{
                        "id": 1,
                        "name": "option",
                        "type": "integer",
                        "mapping": [
                            {"dps_val": value, "value": f"V{value}"}
                            for value in range(65)
                        ],
                    }],
                }
            ])
'''
if "def test_integer_select_projects_friendly_options_and_keeps_typed_raw_mapping" not in test:
    marker = '\n\nif __name__ == "__main__":\n'
    idx = test.find(marker)
    if idx < 0:
        raise SystemExit("test main anchor missing")
    test = test[:idx] + methods + test[idx:]
test_path.write_text(test, encoding="utf-8")

print("typed productless select patch applied")
