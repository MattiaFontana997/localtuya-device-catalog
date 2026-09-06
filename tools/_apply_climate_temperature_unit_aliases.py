from pathlib import Path

path = Path("tools/import_tuya_local_productless.py")
text = path.read_text(encoding="utf-8")

func = r'''

def _exact_temperature_unit_select_mapping(
    entity: dict[str, Any], dp_id: int, *, optional: bool
) -> list[dict[str, Any]] | None:
    """Return an exact sibling temperature-unit select map for one raw DP.

    Cross-entity reuse is intentionally narrow: same numeric DP, string option,
    same optional membership, exactly two explicit raw mappings, and a complete
    Celsius/Fahrenheit friendly domain. Nothing is inferred from naming/case.
    """
    if entity.get("entity") != "select" or entity.get("translation_key") != "temperature_unit":
        return None
    dps = entity.get("dps")
    if not isinstance(dps, list) or len(dps) != 1 or not isinstance(dps[0], dict):
        return None
    dp = dps[0]
    try:
        if base._dp_id(dp) != dp_id or base._dp_type(dp) != "string":
            return None
    except ConversionError:
        return None
    if dp.get("name") != "option" or bool(dp.get("optional")) != optional:
        return None
    if dp.get("force") is True or dp.get("persist") is False or dp.get("sensitive") is True:
        return None
    rules = _raw_mapping(dp)
    if len(rules) != 2:
        return None

    aliases = {
        "C": "celsius", "°C": "celsius", "celsius": "celsius",
        "F": "fahrenheit", "°F": "fahrenheit", "fahrenheit": "fahrenheit",
    }
    normalized: list[dict[str, Any]] = []
    friendly_seen: set[str] = set()
    raw_seen: set[str] = set()
    for rule in rules:
        if set(rule) != {"dps_val", "value"}:
            return None
        raw = rule.get("dps_val")
        friendly = rule.get("value")
        if not isinstance(raw, str) or not isinstance(friendly, str) or friendly not in aliases:
            return None
        friendly = aliases[friendly]
        if raw in raw_seen or friendly in friendly_seen:
            return None
        raw_seen.add(raw)
        friendly_seen.add(friendly)
        normalized.append({"dps_val": raw, "value": friendly})
    if friendly_seen != {"celsius", "fahrenheit"}:
        return None
    return normalized


def _hydrate_climate_temperature_unit_from_sibling(profile: Any) -> Any:
    """Reuse an exact same-DP temperature-unit select map for Climate.

    Some Tuya Local profiles deliberately keep the Climate unit DP unmapped (or
    use a forward default) while a sibling ``temperature_unit`` select on the
    exact same raw DP carries the reversible C/F mapping. The sibling mapping is
    authoritative device evidence, so copying it into the Climate projection is
    lossless. Profiles without that evidence remain unchanged/fail-closed.
    """
    if not isinstance(profile, dict):
        return profile
    entities = profile.get("entities")
    if not isinstance(entities, list):
        return profile

    hydrated = copy.deepcopy(profile)
    hydrated_entities = hydrated.get("entities", [])
    changed = False
    for entity in hydrated_entities:
        if not isinstance(entity, dict) or entity.get("entity") != "climate":
            continue
        dps = entity.get("dps")
        if not isinstance(dps, list):
            continue
        unit = next(
            (
                dp for dp in dps
                if isinstance(dp, dict) and dp.get("name") == "temperature_unit"
            ),
            None,
        )
        if unit is None:
            continue
        try:
            unit_id = base._dp_id(unit)
        except ConversionError:
            continue
        if base._dp_type(unit) != "string":
            continue

        # Leave an already complete exact Climate map alone. The existing
        # normalizer remains the sole validator for it.
        rules = _raw_mapping(unit)
        if rules and all(
            isinstance(rule, dict) and "dps_val" in rule and "value" in rule
            for rule in rules
        ):
            continue

        candidates: list[list[dict[str, Any]]] = []
        for sibling in hydrated_entities:
            if sibling is entity or not isinstance(sibling, dict):
                continue
            candidate = _exact_temperature_unit_select_mapping(
                sibling, unit_id, optional=bool(unit.get("optional"))
            )
            if candidate is not None:
                candidates.append(candidate)
        if len(candidates) != 1:
            continue
        unit["mapping"] = candidates[0]
        changed = True

    return hydrated if changed else profile
'''

anchor = "\n\ndef convert_profile(*args, **kwargs):\n"
if "def _hydrate_climate_temperature_unit_from_sibling(" not in text:
    idx = text.find(anchor)
    if idx < 0:
        raise SystemExit("convert_profile wrapper anchor not found")
    text = text[:idx] + func + text[idx:]

old = '''def convert_profile(*args, **kwargs):\n    return base.convert_profile(*args, **kwargs)\n'''
new = '''def convert_profile(profile, *args, **kwargs):\n    profile = _hydrate_climate_temperature_unit_from_sibling(profile)\n    return base.convert_profile(profile, *args, **kwargs)\n'''
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit("convert_profile wrapper body not found")
path.write_text(text, encoding="utf-8")


test_path = Path("tests/test_import_tuya_local_productless.py")
test = test_path.read_text(encoding="utf-8")
methods = r'''

    def test_climate_temperature_unit_reuses_exact_same_dp_select_mapping(self):
        result = self._convert([
            {
                "entity": "climate",
                "dps": [
                    {
                        "id": 1, "name": "hvac_mode", "type": "string",
                        "mapping": [
                            {"dps_val": "off", "value": "off"},
                            {"dps_val": "cool", "value": "cool"},
                        ],
                    },
                    {"id": 2, "name": "temperature", "type": "integer", "range": {"min": 16, "max": 32}},
                    {"id": 19, "name": "temperature_unit", "type": "string"},
                ],
            },
            {
                "entity": "select", "translation_key": "temperature_unit",
                "dps": [{
                    "id": 19, "name": "option", "type": "string",
                    "mapping": [
                        {"dps_val": "C", "value": "celsius"},
                        {"dps_val": "F", "value": "fahrenheit"},
                    ],
                }],
            },
        ])
        climate = next(e for e in result["entities"] if e["platform"] == "climate")
        self.assertEqual(climate["config"]["temperature_unit_dp"], 19)
        self.assertEqual(
            climate["config"]["temperature_unit_values"],
            {"celsius": "C", "fahrenheit": "F"},
        )

    def test_climate_temperature_unit_replaces_forward_default_only_with_exact_select(self):
        result = self._convert([
            {
                "entity": "climate",
                "dps": [
                    {
                        "id": 1, "name": "hvac_mode", "type": "string",
                        "mapping": [
                            {"dps_val": "off", "value": "off"},
                            {"dps_val": "heat", "value": "heat"},
                        ],
                    },
                    {"id": 2, "name": "temperature", "type": "integer", "range": {"min": 5, "max": 35}},
                    {
                        "id": 19, "name": "temperature_unit", "type": "string",
                        "mapping": [{"dps_val": "f", "value": "F"}, {"value": "C"}],
                    },
                ],
            },
            {
                "entity": "select", "translation_key": "temperature_unit",
                "dps": [{
                    "id": 19, "name": "option", "type": "string",
                    "mapping": [
                        {"dps_val": "f", "value": "fahrenheit"},
                        {"dps_val": "c", "value": "celsius"},
                    ],
                }],
            },
        ])
        climate = next(e for e in result["entities"] if e["platform"] == "climate")
        self.assertEqual(
            climate["config"]["temperature_unit_values"],
            {"fahrenheit": "f", "celsius": "c"},
        )

    def test_climate_temperature_unit_does_not_infer_missing_celsius_raw_value(self):
        with self.assertRaisesRegex(Exception, "climate_temperature_unit_mapping"):
            self._convert([
                {
                    "entity": "climate",
                    "dps": [
                        {
                            "id": 1, "name": "hvac_mode", "type": "string",
                            "mapping": [
                                {"dps_val": "off", "value": "off"},
                                {"dps_val": "heat", "value": "heat"},
                            ],
                        },
                        {"id": 2, "name": "temperature", "type": "integer", "range": {"min": 5, "max": 35}},
                        {
                            "id": 23, "name": "temperature_unit", "type": "string",
                            "mapping": [{"dps_val": "f", "value": "F"}, {"value": "C"}],
                        },
                    ],
                }
            ])

    def test_climate_temperature_unit_rejects_optional_membership_mismatch(self):
        with self.assertRaisesRegex(Exception, "climate_temperature_unit_mapping"):
            self._convert([
                {
                    "entity": "climate",
                    "dps": [
                        {
                            "id": 1, "name": "hvac_mode", "type": "string",
                            "mapping": [
                                {"dps_val": "off", "value": "off"},
                                {"dps_val": "cool", "value": "cool"},
                            ],
                        },
                        {"id": 2, "name": "temperature", "type": "integer", "range": {"min": 16, "max": 32}},
                        {"id": 19, "name": "temperature_unit", "type": "string", "optional": True},
                    ],
                },
                {
                    "entity": "select", "translation_key": "temperature_unit",
                    "dps": [{
                        "id": 19, "name": "option", "type": "string",
                        "mapping": [
                            {"dps_val": "C", "value": "celsius"},
                            {"dps_val": "F", "value": "fahrenheit"},
                        ],
                    }],
                },
            ])
'''
main_anchor = '\n\nif __name__ == "__main__":\n'
if "def test_climate_temperature_unit_reuses_exact_same_dp_select_mapping" not in test:
    idx = test.find(main_anchor)
    if idx < 0:
        raise SystemExit("test main anchor not found")
    test = test[:idx] + methods + test[idx:]
test_path.write_text(test, encoding="utf-8")
print("safe climate temperature-unit sibling alias patch applied")
