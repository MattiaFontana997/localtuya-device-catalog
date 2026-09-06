from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"missing patch anchor in {path}: {old[:100]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


path = "tools/import_tuya_local_productless.py"
replace_once(
    path,
    "import copy\nfrom typing import Any, Callable",
    "import copy\nimport math\nfrom typing import Any, Callable",
)

anchor = '''def _prepare_advanced_entity(\n    entity: dict[str, Any], platform: str\n) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], set[int]]:\n'''
helper = '''def _prepare_climate_limit_precisions(\n    entity: dict[str, Any],\n) -> tuple[dict[str, Any], dict[str, float]]:\n    """Project simple scaled Climate limit DPS onto LocalTuya precision config.\n\n    Tuya Local applies ``scale`` on read for min/max temperature registers.\n    LocalTuya keeps those registers as raw DPS and applies an independent\n    precision multiplier. Only one transform-only ``scale`` rule is accepted;\n    all richer mapping semantics stay fail-closed in the base converter.\n    """\n    transformed = copy.deepcopy(entity)\n    precisions: dict[str, float] = {}\n    for dp in transformed.get("dps", []):\n        if not isinstance(dp, dict) or dp.get("name") not in {"min_temperature", "max_temperature"}:\n            continue\n        rules = _raw_mapping(dp)\n        if not rules:\n            continue\n        if len(rules) != 1 or set(rules[0]) != {"scale"}:\n            continue\n        scale = rules[0].get("scale")\n        if isinstance(scale, bool) or not isinstance(scale, (int, float)):\n            continue\n        scale = float(scale)\n        if not math.isfinite(scale) or scale <= 0:\n            continue\n        key = (\n            "min_temperature_precision"\n            if dp.get("name") == "min_temperature"\n            else "max_temperature_precision"\n        )\n        precisions[key] = 1.0 / scale\n        dp.pop("mapping", None)\n    return transformed, precisions\n\n\n'''
replace_once(path, anchor, helper + anchor)

replace_once(
    path,
    '''        if platform == "climate":\n            flagged = _normalize_climate_temperature_unit(flagged)\n        prepared, advanced_by_dp, membership_ids = _prepare_advanced_entity(\n            flagged, platform\n        )\n''',
    '''        climate_limit_precisions: dict[str, float] = {}\n        if platform == "climate":\n            flagged = _normalize_climate_temperature_unit(flagged)\n            flagged, climate_limit_precisions = _prepare_climate_limit_precisions(flagged)\n        prepared, advanced_by_dp, membership_ids = _prepare_advanced_entity(\n            flagged, platform\n        )\n''',
)

replace_once(
    path,
    '''        converted, required, optional = converter(single, *args, **kwargs)\n\n        if extras:\n''',
    '''        converted, required, optional = converter(single, *args, **kwargs)\n        if climate_limit_precisions:\n            converted["config"].update(climate_limit_precisions)\n\n        if extras:\n''',
)


test_path = Path("tests/test_productless_climate_limits.py")
if not test_path.exists():
    test_path.write_text('''"""Batch N productless Climate scaled limit tests."""\n\nimport unittest\n\nimport import_tuya_local_productless as productless\n\n\nclass ProductlessClimateLimitTests(unittest.TestCase):\n    def test_scaled_min_max_are_projected_to_independent_precision(self):\n        entity = {\n            "entity": "climate",\n            "dps": [\n                {"id": 26, "name": "min_temperature", "type": "integer", "mapping": [{"scale": 10}]},\n                {"id": 19, "name": "max_temperature", "type": "integer", "mapping": [{"scale": 10}]},\n            ],\n        }\n        transformed, precision = productless._prepare_climate_limit_precisions(entity)\n        self.assertEqual(precision, {\n            "min_temperature_precision": 0.1,\n            "max_temperature_precision": 0.1,\n        })\n        self.assertNotIn("mapping", transformed["dps"][0])\n        self.assertNotIn("mapping", transformed["dps"][1])\n        self.assertIn("mapping", entity["dps"][0])\n\n    def test_richer_limit_mapping_remains_for_fail_closed_base_converter(self):\n        entity = {\n            "entity": "climate",\n            "dps": [{\n                "id": 26, "name": "min_temperature", "type": "integer",\n                "mapping": [{"scale": 10, "step": 5}],\n            }],\n        }\n        transformed, precision = productless._prepare_climate_limit_precisions(entity)\n        self.assertEqual(precision, {})\n        self.assertEqual(transformed["dps"][0]["mapping"], [{"scale": 10, "step": 5}])\n\n    def test_invalid_scale_is_not_consumed(self):\n        entity = {\n            "entity": "climate",\n            "dps": [{\n                "id": 26, "name": "min_temperature", "type": "integer",\n                "mapping": [{"scale": 0}],\n            }],\n        }\n        transformed, precision = productless._prepare_climate_limit_precisions(entity)\n        self.assertEqual(precision, {})\n        self.assertIn("mapping", transformed["dps"][0])\n\n\nif __name__ == "__main__":\n    unittest.main()\n''', encoding="utf-8")
