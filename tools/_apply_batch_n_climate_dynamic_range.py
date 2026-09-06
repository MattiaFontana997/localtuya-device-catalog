from pathlib import Path

path = Path("tools/import_tuya_local_productless.py")
text = path.read_text(encoding="utf-8")

func = r'''

def _prepare_climate_dynamic_target_range(
    entity: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Bootstrap the mature Climate converter for condition-only target ranges.

    Tuya Local can make the writable target-temperature range depend on another
    DP through mapping conditions. LocalTuya's advanced runtime reproduces that
    metadata exactly, but the mature converter requires one range while building
    its static config. Inject a conversion-only union range, then discard the
    resulting static min/max constants after conversion so runtime metadata stays
    authoritative. When no condition is active, LocalTuya falls back to HA's
    defaults, matching Tuya Local's ``range() is None`` behaviour.
    """
    transformed = copy.deepcopy(entity)
    dps = transformed.get("dps")
    if not isinstance(dps, list):
        return entity, False

    target = next(
        (
            dp for dp in dps
            if isinstance(dp, dict) and dp.get("name") == "temperature"
        ),
        None,
    )
    if target is None or target.get("range") is not None:
        return entity, False

    rules = _raw_mapping(target)
    if not rules:
        return entity, False

    ranges: list[tuple[float, float]] = []
    saw_conditional_range = False
    for rule in rules:
        # A real static rule range already gives the mature converter an exact
        # fallback, so do not replace it with a synthetic bootstrap range.
        if "range" in rule:
            return entity, False
        conditions = rule.get("conditions")
        if not isinstance(conditions, list):
            continue
        for condition in conditions:
            if not isinstance(condition, dict) or "range" not in condition:
                continue
            saw_conditional_range = True
            value_range = condition.get("range")
            if not isinstance(value_range, dict) or set(value_range) != {"min", "max"}:
                continue
            minimum = value_range.get("min")
            maximum = value_range.get("max")
            if (
                isinstance(minimum, bool)
                or isinstance(maximum, bool)
                or not isinstance(minimum, (int, float))
                or not isinstance(maximum, (int, float))
                or maximum < minimum
            ):
                continue
            ranges.append((float(minimum), float(maximum)))

    # Malformed conditional metadata is intentionally not hidden here. Without
    # a bootstrap range the advanced translator will emit its precise fail-closed
    # validation error before the base converter is called.
    if not saw_conditional_range or not ranges:
        return entity, False

    minimum = min(item[0] for item in ranges)
    maximum = max(item[1] for item in ranges)
    if minimum.is_integer():
        minimum = int(minimum)
    if maximum.is_integer():
        maximum = int(maximum)
    target["range"] = {"min": minimum, "max": maximum}
    return transformed, True
'''

anchor = "\n\ndef _prepare_advanced_entity(\n"
if "def _prepare_climate_dynamic_target_range(" not in text:
    idx = text.find(anchor)
    if idx < 0:
        raise SystemExit("advanced entity anchor not found")
    text = text[:idx] + func + text[idx:]

old = '''        climate_limit_precisions: dict[str, float] = {}\n        if platform == "climate":\n            flagged = _normalize_climate_temperature_unit(flagged)\n            flagged, climate_limit_precisions = _prepare_climate_limit_precisions(flagged)\n        prepared, advanced_by_dp, membership_ids = _prepare_advanced_entity(\n'''
new = '''        climate_limit_precisions: dict[str, float] = {}\n        climate_dynamic_target_range = False\n        if platform == "climate":\n            flagged = _normalize_climate_temperature_unit(flagged)\n            flagged, climate_limit_precisions = _prepare_climate_limit_precisions(flagged)\n            flagged, climate_dynamic_target_range = _prepare_climate_dynamic_target_range(flagged)\n        prepared, advanced_by_dp, membership_ids = _prepare_advanced_entity(\n'''
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit("climate wrapper preparation anchor not found")

old2 = '''        converted, required, optional = converter(single, *args, **kwargs)\n        if climate_limit_precisions:\n            converted["config"].update(climate_limit_precisions)\n\n        for mapped_dp, rules in complex_mapped_extras:\n'''
new2 = '''        converted, required, optional = converter(single, *args, **kwargs)\n        if climate_limit_precisions:\n            converted["config"].update(climate_limit_precisions)\n        if climate_dynamic_target_range:\n            # The injected union range existed only to satisfy the mature\n            # converter. Runtime advanced metadata owns the actual active range.\n            converted["config"].pop("min_temperature_const", None)\n            converted["config"].pop("max_temperature_const", None)\n\n        for mapped_dp, rules in complex_mapped_extras:\n'''
if old2 in text:
    text = text.replace(old2, new2, 1)
elif new2 not in text:
    raise SystemExit("climate wrapper post-conversion anchor not found")

path.write_text(text, encoding="utf-8")


test_path = Path("tests/test_import_tuya_local_productless.py")
test = test_path.read_text(encoding="utf-8")
method = r'''

    def test_climate_conditional_target_range_is_runtime_authoritative(self):
        result = self._convert([
            {
                "entity": "climate",
                "dps": [
                    {
                        "id": 1,
                        "name": "hvac_mode",
                        "type": "string",
                        "mapping": [
                            {"dps_val": "off", "value": "off"},
                            {"dps_val": "heat", "value": "heat"},
                        ],
                    },
                    {
                        "id": 2,
                        "name": "temperature",
                        "type": "integer",
                        "mapping": [
                            {
                                "scale": 10,
                                "constraint": "mode",
                                "conditions": [
                                    {
                                        "dps_val": "cold",
                                        "range": {"min": 170, "max": 300},
                                    },
                                    {
                                        "dps_val": "hot",
                                        "range": {"min": 0, "max": 300},
                                    },
                                    {"dps_val": "wind", "invalid": True},
                                ],
                            }
                        ],
                    },
                    {"id": 4, "name": "mode", "type": "string", "hidden": True},
                ],
            }
        ])
        config = result["entities"][0]["config"]
        self.assertEqual(config["target_temperature_dp"], 2)
        self.assertEqual(config["target_precision"], 0.1)
        self.assertNotIn("min_temperature_const", config)
        self.assertNotIn("max_temperature_const", config)
        self.assertEqual(
            config["advanced_mapping_by_dp"]["2"],
            [
                {
                    "constraint_dp": 4,
                    "conditions": [
                        {"dps_val": "cold", "range": {"min": 170, "max": 300}},
                        {"dps_val": "hot", "range": {"min": 0, "max": 300}},
                        {"dps_val": "wind", "invalid": True},
                    ],
                }
            ],
        )
        self.assertEqual(result["match"]["required_dps"], [1, 2, 4])

    def test_climate_static_target_range_keeps_static_limits(self):
        result = self._convert([
            {
                "entity": "climate",
                "dps": [
                    {
                        "id": 1,
                        "name": "hvac_mode",
                        "type": "string",
                        "mapping": [
                            {"dps_val": "off", "value": "off"},
                            {"dps_val": "heat", "value": "heat"},
                        ],
                    },
                    {
                        "id": 2,
                        "name": "temperature",
                        "type": "integer",
                        "range": {"min": 5, "max": 35},
                    },
                ],
            }
        ])
        config = result["entities"][0]["config"]
        self.assertEqual(config["min_temperature_const"], 5.0)
        self.assertEqual(config["max_temperature_const"], 35.0)
'''

main_anchor = '\n\nif __name__ == "__main__":\n'
if "def test_climate_conditional_target_range_is_runtime_authoritative" not in test:
    idx = test.find(main_anchor)
    if idx < 0:
        raise SystemExit("test main anchor not found")
    test = test[:idx] + method + test[idx:]

test_path.write_text(test, encoding="utf-8")
print("Batch N climate dynamic range importer patch applied")
