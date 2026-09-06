from pathlib import Path

path = Path('tools/import_tuya_local_productless.py')
text = path.read_text(encoding='utf-8')

text = text.replace(
    '_RUNTIME_CONDITION_KEYS = {"dps_val", "value", "hidden", "invalid", "value_redirect"}',
    '_RUNTIME_CONDITION_KEYS = {"dps_val", "value", "hidden", "invalid", "value_redirect", "range", "step"}',
    1,
)

old = '''def _translate_advanced_mapping(\n    dp: dict[str, Any],\n    by_name: dict[str, dict[str, Any]],\n) -> tuple[list[dict[str, Any]], set[str]]:'''
new = '''def _translate_advanced_mapping(\n    dp: dict[str, Any],\n    by_name: dict[str, dict[str, Any]],\n    platform: str,\n) -> tuple[list[dict[str, Any]], set[str]]:'''
if old not in text:
    raise SystemExit('translate signature marker missing')
text = text.replace(old, new, 1)

old = '''        if set(source) & transform_keys:\n            raise ConversionError("advanced_mapping_rule_transform_semantics")'''
new = '''        # Static mapping transforms remain in the mature base converter.  Do not\n        # duplicate them into advanced_mapping_by_dp or values would be transformed\n        # twice.  Batch M only overlays condition-dependent metadata below.\n        # Invert/target_range are still rejected when mixed with advanced semantics\n        # because their exact transform range differs from the active metadata range.\n        if set(source) & {"invert", "target_range"}:\n            raise ConversionError("advanced_mapping_rule_transform_semantics")'''
if old not in text:
    raise SystemExit('source transform rejection marker missing')
text = text.replace(old, new, 1)

old = '''                if set(condition) - _RUNTIME_CONDITION_KEYS:\n                    # Dynamic scale/range/step changes also alter HA limits and\n                    # precision in Tuya Local. LocalTuya 6.4 has static entity\n                    # metadata for those, so importing them would only be partial.\n                    raise ConversionError("advanced_mapping_condition_semantics")'''
new = '''                if set(condition) - _RUNTIME_CONDITION_KEYS:\n                    raise ConversionError("advanced_mapping_condition_semantics")\n                dynamic_metadata = set(condition) & {"range", "step"}\n                if dynamic_metadata and platform not in {"climate", "number"}:\n                    raise ConversionError("advanced_mapping_condition_semantics")'''
if old not in text:
    raise SystemExit('condition semantics marker missing')
text = text.replace(old, new, 1)

old = '''                for key in ("hidden", "invalid"):\n                    if key in condition:\n                        if not isinstance(condition[key], bool):\n                            raise ConversionError("advanced_mapping_condition_boolean")\n                        out[key] = condition[key]\n                condition_redirect = condition.get("value_redirect")'''
new = '''                for key in ("hidden", "invalid"):\n                    if key in condition:\n                        if not isinstance(condition[key], bool):\n                            raise ConversionError("advanced_mapping_condition_boolean")\n                        out[key] = condition[key]\n                if "range" in condition:\n                    value_range = condition["range"]\n                    if (\n                        not isinstance(value_range, dict)\n                        or set(value_range) != {"min", "max"}\n                        or any(isinstance(value_range[k], bool) or not isinstance(value_range[k], (int, float)) for k in ("min", "max"))\n                        or value_range["max"] < value_range["min"]\n                    ):\n                        raise ConversionError("advanced_mapping_condition_range")\n                    out["range"] = {"min": value_range["min"], "max": value_range["max"]}\n                if "step" in condition:\n                    step = condition["step"]\n                    if isinstance(step, bool) or not isinstance(step, (int, float)) or step <= 0:\n                        raise ConversionError("advanced_mapping_condition_step")\n                    out["step"] = step\n                condition_redirect = condition.get("value_redirect")'''
if old not in text:
    raise SystemExit('condition output marker missing')
text = text.replace(old, new, 1)

old = 'translated, references = _translate_advanced_mapping(original_dp, by_name)'
new = 'translated, references = _translate_advanced_mapping(original_dp, by_name, platform)'
if old not in text:
    raise SystemExit('translate call marker missing')
text = text.replace(old, new, 1)

old = '''        conditions = source.get("conditions")\n        if isinstance(conditions, list) and conditions:\n            for condition in conditions:\n                if not isinstance(condition, dict):\n                    raise ConversionError("advanced_mapping_condition")\n                if condition.get("invalid") is True or condition.get("hidden") is True:\n                    continue\n                add_output(condition.get(\n                    "value", source.get("value", source.get("dps_val", missing))\n                ))\n        else:\n            add_output(source.get("value", source.get("dps_val", missing)))'''
new = '''        conditions = source.get("conditions")\n        if isinstance(conditions, list) and conditions:\n            # Tuya Local exposes the mapping's own value first, then any visible\n            # condition-specific values.  Invalid-only conditions therefore must\n            # not erase an otherwise valid base enum value.\n            if "value" in source:\n                add_output(source["value"])\n            for condition in conditions:\n                if not isinstance(condition, dict):\n                    raise ConversionError("advanced_mapping_condition")\n                if condition.get("invalid") is True or condition.get("hidden") is True:\n                    continue\n                if "value" in condition:\n                    add_output(condition["value"])\n                elif "value" in source:\n                    add_output(source["value"])\n        else:\n            add_output(source.get("value", source.get("dps_val", missing)))'''
if old not in text:
    raise SystemExit('projection marker missing')
text = text.replace(old, new, 1)

path.write_text(text, encoding='utf-8')

test = Path('tests/test_productless_advanced_mapping_v2.py')
test.write_text('''"""Batch M conditional metadata and enum projection tests."""\n\nimport unittest\n\nimport import_tuya_local_productless as productless\n\n\nclass ProductlessAdvancedMappingV2Tests(unittest.TestCase):\n    def test_invalid_only_condition_keeps_base_enum_value(self):\n        dp = {\n            "id": 4, "type": "string", "name": "fan_mode",\n            "mapping": [\n                {"dps_val": "Low", "value": "low", "constraint": "mode",\n                 "conditions": [{"dps_val": "Auto", "invalid": True}]},\n                {"dps_val": "High", "value": "high", "constraint": "mode",\n                 "conditions": [{"dps_val": "Auto", "invalid": True}]},\n            ],\n        }\n        projected = productless._project_mapping_for_base(dp, "climate", "fan_mode")\n        self.assertEqual(projected["mapping"], [\n            {"dps_val": "low", "value": "low"},\n            {"dps_val": "high", "value": "high"},\n        ])\n\n    def test_climate_condition_range_and_step_are_translated(self):\n        dp = {\n            "id": 16, "type": "integer", "name": "temperature",\n            "range": {"min": 50, "max": 400},\n            "mapping": [{\n                "scale": 10, "step": 5, "constraint": "temperature_unit",\n                "conditions": [{"dps_val": True, "range": {"min": 410, "max": 1040}, "step": 10}],\n            }],\n        }\n        unit = {"id": 107, "type": "boolean", "name": "temperature_unit"}\n        rules, refs = productless._translate_advanced_mapping(\n            dp, {"temperature": dp, "temperature_unit": unit}, "climate"\n        )\n        self.assertEqual(refs, {"temperature_unit"})\n        self.assertEqual(rules[0]["conditions"][0]["range"], {"min": 410, "max": 1040})\n        self.assertEqual(rules[0]["conditions"][0]["step"], 10)\n        self.assertNotIn("scale", rules[0])\n        self.assertNotIn("step", rules[0])\n\n    def test_fan_dynamic_step_remains_fail_closed(self):\n        dp = {\n            "id": 2, "type": "integer", "name": "speed",\n            "mapping": [{"constraint": "preset_mode", "conditions": [{"dps_val": "sleep", "step": 4}]}],\n        }\n        preset = {"id": 3, "type": "string", "name": "preset_mode"}\n        with self.assertRaisesRegex(Exception, "advanced_mapping_condition_semantics"):\n            productless._translate_advanced_mapping(dp, {"speed": dp, "preset_mode": preset}, "fan")\n\n    def test_condition_scale_stays_fail_closed(self):\n        dp = {\n            "id": 2, "type": "integer", "name": "temperature",\n            "mapping": [{"constraint": "mode", "conditions": [{"dps_val": "x", "scale": 10}]}],\n        }\n        mode = {"id": 3, "type": "string", "name": "mode"}\n        with self.assertRaisesRegex(Exception, "advanced_mapping_condition_semantics"):\n            productless._translate_advanced_mapping(dp, {"temperature": dp, "mode": mode}, "climate")\n\n\nif __name__ == "__main__":\n    unittest.main()\n''', encoding='utf-8')
