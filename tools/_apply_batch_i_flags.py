from pathlib import Path

path = Path('tools/import_tuya_local_productless.py')
text = path.read_text(encoding='utf-8')

marker = '\n\ndef _advanced_wrapper(\n'
insert = r'''


def _prepare_runtime_flags(
    entity: dict[str, Any], platform: str
) -> tuple[dict[str, Any], bool, set[str], set[int]]:
    """Project Tuya Local hidden/force/persist semantics onto catalog runtime.

    ``force`` is consumed because every DP that survives conversion is already
    explicitly requested by LocalTuya. ``hidden`` on entity means disabled by
    default; hidden DPs remain in fingerprint membership but are not exposed as
    extra attributes. ``persist: false`` is carried to the runtime cache policy.
    """
    transformed = copy.deepcopy(entity)
    entity_hidden = transformed.get("hidden")
    disabled_default = False
    if entity_hidden is True:
        disabled_default = True
        transformed.pop("hidden", None)
    elif entity_hidden in (None, False):
        transformed.pop("hidden", None)
    elif entity_hidden == "unavailable":
        raise ConversionError("entity_hidden_unavailable")
    else:
        raise ConversionError("entity_hidden")

    hidden_extra_names: set[str] = set()
    non_persistent_dps: set[int] = set()
    dps = transformed.get("dps")
    if isinstance(dps, list):
        for dp in dps:
            if not isinstance(dp, dict):
                continue
            name = dp.get("name")
            if dp.get("hidden") is True:
                if isinstance(name, str) and name:
                    hidden_extra_names.add(name)
                dp.pop("hidden", None)
            elif dp.get("hidden") not in (None, False):
                raise ConversionError("dp_hidden")
            else:
                dp.pop("hidden", None)

            force = dp.get("force")
            if force is True:
                # LocalTuya requests every declared/consumed catalog DP.
                dp.pop("force", None)
            elif force not in (None, False):
                raise ConversionError("dp_force")
            else:
                dp.pop("force", None)

            if dp.get("persist") is False:
                non_persistent_dps.add(base._dp_id(dp))
                dp.pop("persist", None)
            elif dp.get("persist") in (None, True):
                dp.pop("persist", None)
            else:
                raise ConversionError("dp_persist")

    return transformed, disabled_default, hidden_extra_names, non_persistent_dps


def _apply_runtime_flags(
    converted: dict[str, Any],
    *,
    disabled_default: bool,
    hidden_extra_names: set[str],
    non_persistent_dps: set[int],
) -> None:
    config = converted["config"]
    if disabled_default:
        config["entity_registry_enabled_default"] = False

    extras = config.get("extra_state_attributes_dps")
    if isinstance(extras, dict) and hidden_extra_names:
        for name in hidden_extra_names:
            extras.pop(name, None)
        if not extras:
            config.pop("extra_state_attributes_dps", None)

    if non_persistent_dps:
        config["non_persistent_dps"] = sorted(non_persistent_dps)
'''
if '_prepare_runtime_flags' not in text:
    if marker not in text:
        raise SystemExit('advanced wrapper marker not found')
    text = text.replace(marker, insert + marker, 1)

old = '''    def wrapped(entity: dict[str, Any], *args, **kwargs) -> base.Converted:\n        prepared, advanced_by_dp, membership_ids = _prepare_advanced_entity(\n            entity, platform\n        )\n        single, extras = _split_simple_multi_dp_entity(prepared, platform)\n        converted, required, optional = converter(single, *args, **kwargs)'''
new = '''    def wrapped(entity: dict[str, Any], *args, **kwargs) -> base.Converted:\n        flagged, disabled_default, hidden_extra_names, non_persistent_dps = (\n            _prepare_runtime_flags(entity, platform)\n        )\n        prepared, advanced_by_dp, membership_ids = _prepare_advanced_entity(\n            flagged, platform\n        )\n        single, extras = _split_simple_multi_dp_entity(prepared, platform)\n        converted, required, optional = converter(single, *args, **kwargs)'''
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit('wrapper start marker not found')

old = '''        if not advanced_by_dp:\n            return converted, required, optional\n\n        converted["config"]["advanced_mapping_by_dp"] = advanced_by_dp'''
new = '''        _apply_runtime_flags(\n            converted,\n            disabled_default=disabled_default,\n            hidden_extra_names=hidden_extra_names,\n            non_persistent_dps=non_persistent_dps,\n        )\n\n        if not advanced_by_dp:\n            return converted, required, optional\n\n        converted["config"]["advanced_mapping_by_dp"] = advanced_by_dp'''
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit('wrapper return marker not found')

old = '''base._CONVERTERS.update({\n    "time": _convert_time,\n    "event": _convert_event,\n})'''
new = '''base._CONVERTERS.update({\n    "time": _advanced_wrapper("time", _convert_time),\n    "event": _advanced_wrapper("event", _convert_event),\n})'''
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit('time/event converter marker not found')

path.write_text(text, encoding='utf-8')

# Batch G intentionally failed closed on force before Batch I established that
# every retained catalog DP is already explicitly requested by LocalTuya.
test_path = Path('tests/test_import_tuya_local_productless.py')
test_text = test_path.read_text(encoding='utf-8')
old_test = '''    def test_multidp_extra_force_stays_fail_closed(self):\n        with self.assertRaisesRegex(ConversionError, "sensor_extra_semantics:calibration"):\n            self._convert([\n                {\n                    "entity": "sensor",\n                    "dps": [\n                        {"id": 1, "name": "sensor", "type": "integer"},\n                        {"id": 2, "name": "calibration", "type": "integer", "force": True},\n                    ],\n                }\n            ])\n'''
new_test = '''    def test_multidp_extra_force_is_preserved_as_requested_attribute(self):\n        result = self._convert([\n            {\n                "entity": "sensor",\n                "dps": [\n                    {"id": 1, "name": "sensor", "type": "integer"},\n                    {"id": 2, "name": "calibration", "type": "integer", "force": True},\n                ],\n            }\n        ])\n        self.assertEqual(\n            result["entities"][0]["config"]["extra_state_attributes_dps"],\n            {"calibration": 2},\n        )\n        self.assertEqual(result["match"]["required_dps"], [1, 2])\n'''
if old_test in test_text:
    test_text = test_text.replace(old_test, new_test, 1)
elif new_test not in test_text:
    raise SystemExit('Batch G force test marker not found')
test_path.write_text(test_text, encoding='utf-8')
