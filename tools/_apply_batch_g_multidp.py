from pathlib import Path

MODULE = Path("tools/import_tuya_local_productless.py")
TESTS = Path("tests/test_import_tuya_local_productless.py")

text = MODULE.read_text(encoding="utf-8")
start = text.index("def _advanced_wrapper(")
end = text.index("\n\ndef _simple_time_component", start)
replacement = '''def _advanced_dependency_ids(advanced_by_dp: dict[str, list[dict[str, Any]]]) -> set[int]:
    """Return DPS referenced only as advanced-mapping dependencies."""
    result: set[int] = set()
    for rules in advanced_by_dp.values():
        for rule in rules:
            for key in ("constraint_dp", "value_redirect_dp"):
                value = rule.get(key)
                if value is not None:
                    result.add(int(value))
            for condition in rule.get("conditions", []):
                if not isinstance(condition, dict):
                    continue
                value = condition.get("value_redirect_dp")
                if value is not None:
                    result.add(int(value))
    return result


def _split_simple_multi_dp_entity(
    entity: dict[str, Any], platform: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Split a simple entity into one functional DP plus lossless raw extras.

    Tuya Local exposes unconsumed DPS as extra state attributes. LocalTuya can
    represent the same raw attributes through ``extra_state_attributes_dps``.
    Batch G therefore permits multiple DPS only for the simple platforms whose
    mature converter has exactly one functional DP.
    """
    primary_name = _SIMPLE_PRIMARY_NAMES.get(platform)
    dps = entity.get("dps")
    if primary_name is None or not isinstance(dps, list) or len(dps) <= 1:
        return entity, []

    named: dict[str, dict[str, Any]] = {}
    for dp in dps:
        if not isinstance(dp, dict):
            raise ConversionError("invalid_dp")
        name = dp.get("name")
        if not isinstance(name, str) or not name:
            raise ConversionError(f"{platform}_missing_dp_name")
        if name in named:
            raise ConversionError(f"{platform}_duplicate_dp:{name}")
        named[name] = dp

    primary = named.get(primary_name)
    if primary is None:
        raise ConversionError(f"expected_dp_name:{primary_name}")

    # Duplicate raw DP aliases are safe only when they agree on required vs
    # optional membership. The raw value may then be exposed under another
    # attribute name without requesting a contradictory fingerprint state.
    primary_id = base._dp_id(primary)
    primary_membership = base._dp_membership(primary)
    for dp in dps:
        if dp is primary:
            continue
        if base._dp_id(dp) == primary_id and base._dp_membership(dp) != primary_membership:
            raise ConversionError("multi_dp_membership_conflict")

    single = copy.deepcopy(entity)
    single["dps"] = [copy.deepcopy(primary)]
    extras = [copy.deepcopy(dp) for dp in dps if dp is not primary]
    return single, extras


def _preserve_simple_multi_dp_extras(
    platform: str,
    extras: list[dict[str, Any]],
    advanced_by_dp: dict[str, list[dict[str, Any]]],
    config: dict[str, Any],
    required: set[int],
    optional: set[int],
) -> None:
    dependency_ids = _advanced_dependency_ids(advanced_by_dp)
    advanced_source_ids = {int(dp_id) for dp_id in advanced_by_dp}
    exposed = len(config.get("extra_state_attributes_dps", {}))

    for dp in extras:
        dp_id = base._dp_id(dp)
        name = dp.get("name")
        if not isinstance(name, str) or not name:
            raise ConversionError(f"{platform}_missing_dp_name")

        # Constraint/redirect DPS are internal to Batch F and already retained
        # in fingerprint membership. Do not expose them as unrelated raw attrs.
        if dp_id in dependency_ids:
            continue

        # An extra DP with its own advanced mapping has HA-facing semantics of
        # its own. Treating it as a raw attribute would silently discard them.
        if dp_id in advanced_source_ids:
            raise ConversionError(f"multi_dp_advanced_extra:{name}")

        will_expose = dp.get("hidden") is not True and name not in {"state", "available"}
        if will_expose:
            exposed += 1
            if exposed > 32:
                raise ConversionError("multi_dp_too_many_extra_attributes")

        base._preserve_core_extra(
            platform, name, dp, config, required, optional
        )


def _advanced_wrapper(
    platform: str, converter: Callable[..., base.Converted]
) -> Callable[..., base.Converted]:
    def wrapped(entity: dict[str, Any], *args, **kwargs) -> base.Converted:
        prepared, advanced_by_dp, membership_ids = _prepare_advanced_entity(
            entity, platform
        )
        single, extras = _split_simple_multi_dp_entity(prepared, platform)
        converted, required, optional = converter(single, *args, **kwargs)

        if extras:
            _preserve_simple_multi_dp_extras(
                platform,
                extras,
                advanced_by_dp,
                converted["config"],
                required,
                optional,
            )

        if not advanced_by_dp:
            return converted, required, optional

        converted["config"]["advanced_mapping_by_dp"] = advanced_by_dp
        originals = {
            base._dp_id(dp): dp
            for dp in entity.get("dps", [])
            if isinstance(dp, dict)
        }
        for dp_id in membership_ids:
            dp = originals.get(dp_id)
            if dp is None:
                raise ConversionError("advanced_mapping_dependency_missing_dp")
            base._merge_membership(required, optional, dp)
        return converted, required, optional

    return wrapped
'''
text = text[:start] + replacement + text[end:]
MODULE.write_text(text, encoding="utf-8")


tests = TESTS.read_text(encoding="utf-8")
marker = '\n\nif __name__ == "__main__":\n'
if marker not in tests:
    raise SystemExit("test marker not found")
if "test_multidp_sensor_preserves_raw_extras" in tests:
    raise SystemExit("Batch G tests already present")
methods = r'''
    def test_multidp_sensor_preserves_raw_extras(self):
        result = self._convert([
            {
                "entity": "sensor",
                "class": "energy",
                "dps": [
                    {
                        "id": 109,
                        "name": "sensor",
                        "type": "integer",
                        "unit": "kWh",
                        "class": "total_increasing",
                        "mapping": [{"scale": 100}],
                    },
                    {"id": 104, "name": "unknown_104", "type": "integer"},
                    {"id": 105, "name": "unknown_105", "type": "integer", "optional": True},
                ],
            }
        ])
        config = result["entities"][0]["config"]
        self.assertEqual(
            config["extra_state_attributes_dps"],
            {"unknown_104": 104, "unknown_105": 105},
        )
        self.assertEqual(result["match"]["required_dps"], [104, 109])
        self.assertEqual(result["match"]["optional_dps"], [105])

    def test_multidp_switch_preserves_raw_diagnostics(self):
        result = self._convert([
            {
                "entity": "switch",
                "dps": [
                    {"id": 1, "name": "switch", "type": "boolean"},
                    {"id": 21, "name": "test_bit", "type": "integer"},
                    {"id": 43, "name": "inching", "type": "base64"},
                ],
            }
        ])
        config = result["entities"][0]["config"]
        self.assertEqual(
            config["extra_state_attributes_dps"],
            {"test_bit": 21, "inching": 43},
        )
        self.assertEqual(result["match"]["required_dps"], [1, 21, 43])

    def test_multidp_number_preserves_raw_companion_values(self):
        result = self._convert([
            {
                "entity": "number",
                "dps": [
                    {"id": 14, "name": "value", "type": "integer", "range": {"min": 1, "max": 10}},
                    {"id": 104, "name": "meal_plan", "type": "string"},
                    {"id": 102, "name": "unknown_102", "type": "boolean"},
                ],
            }
        ])
        self.assertEqual(
            result["entities"][0]["config"]["extra_state_attributes_dps"],
            {"meal_plan": 104, "unknown_102": 102},
        )

    def test_multidp_select_preserves_raw_companion_values(self):
        result = self._convert([
            {
                "entity": "select",
                "dps": [
                    {
                        "id": 101,
                        "name": "option",
                        "type": "string",
                        "mapping": [
                            {"dps_val": "a", "value": "A"},
                            {"dps_val": "b", "value": "B"},
                        ],
                    },
                    {"id": 104, "name": "recently", "type": "integer"},
                    {"id": 111, "name": "recent_love", "type": "integer"},
                ],
            }
        ])
        self.assertEqual(
            result["entities"][0]["config"]["extra_state_attributes_dps"],
            {"recently": 104, "recent_love": 111},
        )

    def test_multidp_binary_sensor_preserves_raw_selftest(self):
        result = self._convert([
            {
                "entity": "binary_sensor",
                "dps": [
                    {
                        "id": 1,
                        "name": "sensor",
                        "type": "string",
                        "mapping": [
                            {"dps_val": "presence", "value": True},
                            {"dps_val": "none", "value": False},
                        ],
                    },
                    {"id": 6, "name": "selftest_result", "type": "string"},
                ],
            }
        ])
        self.assertEqual(
            result["entities"][0]["config"]["extra_state_attributes_dps"],
            {"selftest_result": 6},
        )

    def test_multidp_extra_mapping_stays_fail_closed(self):
        with self.assertRaisesRegex(ConversionError, "sensor_extra_mapping:description"):
            self._convert([
                {
                    "entity": "sensor",
                    "dps": [
                        {"id": 1, "name": "sensor", "type": "integer"},
                        {
                            "id": 2,
                            "name": "description",
                            "type": "string",
                            "mapping": [{"dps_val": "x", "value": "friendly"}],
                        },
                    ],
                }
            ])

    def test_multidp_extra_force_stays_fail_closed(self):
        with self.assertRaisesRegex(ConversionError, "sensor_extra_semantics:calibration"):
            self._convert([
                {
                    "entity": "sensor",
                    "dps": [
                        {"id": 1, "name": "sensor", "type": "integer"},
                        {"id": 2, "name": "calibration", "type": "integer", "force": True},
                    ],
                }
            ])

    def test_multidp_duplicate_raw_dp_alias_is_preserved(self):
        result = self._convert([
            {
                "entity": "binary_sensor",
                "dps": [
                    {"id": 10, "name": "sensor", "type": "boolean"},
                    {"id": 10, "name": "fault_code", "type": "boolean"},
                ],
            }
        ])
        self.assertEqual(
            result["entities"][0]["config"]["extra_state_attributes_dps"],
            {"fault_code": 10},
        )
        self.assertEqual(result["match"]["required_dps"], [10])

    def test_multidp_duplicate_alias_membership_conflict_rejected(self):
        with self.assertRaisesRegex(ConversionError, "multi_dp_membership_conflict"):
            self._convert([
                {
                    "entity": "switch",
                    "dps": [
                        {"id": 1, "name": "switch", "type": "boolean"},
                        {"id": 1, "name": "available", "type": "boolean", "optional": True},
                    ],
                }
            ])
'''
TESTS.write_text(tests.replace(marker, '\n' + methods + marker), encoding="utf-8")
