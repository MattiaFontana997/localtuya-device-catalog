from pathlib import Path

path = Path('tools/import_tuya_local_productless.py')
text = path.read_text()
helper = r'''
_ALARM_STATES = {
    "disarmed", "armed_home", "armed_away", "armed_night", "armed_vacation",
    "armed_custom_bypass", "pending", "arming", "disarming", "triggered",
}


def _plain_raw_scalar(value: Any, raw_type: str, reason: str) -> str | int | bool:
    if raw_type == "string" and isinstance(value, str):
        return value
    if raw_type == "integer" and isinstance(value, int) and not isinstance(value, bool):
        return value
    if raw_type == "boolean" and isinstance(value, bool):
        return value
    raise ConversionError(reason)


def _convert_alarm_control_panel_productless(entity: dict[str, Any]) -> base.Converted:
    """Convert exact Tuya Local alarm-state/trigger semantics."""
    dps = _named_dps(entity, "alarm_control_panel")
    state = dps.get("alarm_state")
    if state is None:
        raise ConversionError("alarm_missing_state")
    base._check_common_dp_semantics(state, writable=True)
    raw_type = base._dp_type(state)
    if raw_type not in {"string", "integer", "boolean"}:
        raise ConversionError("alarm_state_type")
    rules = _raw_mapping(state)
    if not rules:
        raise ConversionError("alarm_state_mapping")
    values: dict[str, Any] = {}
    raw_seen: list[Any] = []
    for rule in rules:
        if set(rule) - {"dps_val", "value", "hidden"} or rule.get("hidden") is True:
            raise ConversionError("alarm_state_mapping")
        if "dps_val" not in rule or "value" not in rule:
            raise ConversionError("alarm_state_mapping")
        friendly = rule["value"]
        if not isinstance(friendly, str) or friendly not in _ALARM_STATES:
            raise ConversionError("alarm_state_mapping")
        raw = _plain_raw_scalar(rule["dps_val"], raw_type, "alarm_state_mapping")
        if friendly in values or any(raw == old and type(raw) is type(old) for old in raw_seen):
            raise ConversionError("alarm_state_duplicate")
        values[friendly] = raw
        raw_seen.append(raw)

    config: dict[str, Any] = {
        "id": base._dp_id(state),
        "platform": "alarm_control_panel",
        "alarm_state_dp": base._dp_id(state),
        "alarm_state_values": values,
    }
    base._entity_metadata(entity, config)
    required: set[int] = set()
    optional: set[int] = set()
    base._merge_membership(required, optional, state)

    trigger = dps.get("trigger")
    if trigger is not None:
        raw_on, raw_off = base._core_boolean_values(
            trigger, reason="alarm_trigger", writable=True
        )
        config["alarm_trigger_dp"] = base._dp_id(trigger)
        config["alarm_trigger_on"] = raw_on
        config["alarm_trigger_off"] = raw_off
        base._merge_membership(required, optional, trigger)

    for name, dp in dps.items():
        if name in {"alarm_state", "trigger"}:
            continue
        base._preserve_core_extra(
            "alarm_control_panel", name, dp, config, required, optional
        )
    return {"platform": "alarm_control_panel", "config": config}, required, optional


def _convert_siren_productless(entity: dict[str, Any]) -> base.Converted:
    """Convert static Tuya Local Siren controls without changing raw semantics."""
    dps = _named_dps(entity, "siren")
    functional = {"switch", "tone", "volume_level", "duration"}
    primary = next((dps[name] for name in ("switch", "tone", "volume_level", "duration") if name in dps), None)
    if primary is None:
        raise ConversionError("siren_missing_functional_dp")
    config: dict[str, Any] = {"id": base._dp_id(primary), "platform": "siren"}
    base._entity_metadata(entity, config)
    required: set[int] = set()
    optional: set[int] = set()

    switch = dps.get("switch")
    if switch is not None:
        raw_on, raw_off = base._core_boolean_values(switch, reason="siren_switch", writable=True)
        config.update({
            "id": base._dp_id(switch),
            "siren_switch_dp": base._dp_id(switch),
            "siren_switch_on": raw_on,
            "siren_switch_off": raw_off,
        })
        base._merge_membership(required, optional, switch)

    tone = dps.get("tone")
    if tone is not None:
        base._check_common_dp_semantics(tone, writable=True)
        raw_type = base._dp_type(tone)
        if raw_type not in {"string", "integer"}:
            raise ConversionError("siren_tone_type")
        values: dict[str, Any] = {}
        raw_seen: list[Any] = []
        default_tone = None
        for rule in _raw_mapping(tone):
            if set(rule) - {"dps_val", "value", "default", "hidden"} or rule.get("hidden") is True:
                raise ConversionError("siren_tone_mapping")
            if "dps_val" not in rule or "value" not in rule:
                raise ConversionError("siren_tone_mapping")
            friendly = rule["value"]
            if not isinstance(friendly, str) or not friendly.strip():
                raise ConversionError("siren_tone_mapping")
            friendly = friendly.strip()
            raw = _plain_raw_scalar(rule["dps_val"], raw_type, "siren_tone_mapping")
            if friendly in values or any(raw == old and type(raw) is type(old) for old in raw_seen):
                raise ConversionError("siren_tone_duplicate")
            values[friendly] = raw
            raw_seen.append(raw)
            if rule.get("default") is True:
                if default_tone is not None or friendly == "off":
                    raise ConversionError("siren_tone_default")
                default_tone = friendly
            elif rule.get("default") not in (None, False):
                raise ConversionError("siren_tone_default")
        if not values:
            raise ConversionError("siren_tone_mapping")
        if "off" not in values and switch is None:
            raise ConversionError("siren_tone_missing_off")
        if default_tone is None:
            non_off = [name for name in values if name != "off"]
            if len(non_off) == 1:
                default_tone = non_off[0]
            elif switch is None:
                raise ConversionError("siren_tone_default")
        config["siren_tone_dp"] = base._dp_id(tone)
        config["siren_tone_values"] = values
        if default_tone is not None:
            config["siren_default_tone"] = default_tone
        base._merge_membership(required, optional, tone)

    volume = dps.get("volume_level")
    if volume is not None:
        base._check_common_dp_semantics(volume, writable=True)
        raw_type = base._dp_type(volume)
        rules = _raw_mapping(volume)
        if rules:
            values: dict[str, Any] = {}
            raw_seen: list[Any] = []
            for rule in rules:
                if set(rule) != {"dps_val", "value"}:
                    raise ConversionError("siren_volume_mapping")
                friendly = rule["value"]
                if isinstance(friendly, bool) or not isinstance(friendly, (int, float)):
                    raise ConversionError("siren_volume_mapping")
                level = float(friendly)
                if not 0.0 <= level <= 1.0:
                    raise ConversionError("siren_volume_mapping")
                raw = _plain_raw_scalar(rule["dps_val"], raw_type, "siren_volume_mapping")
                key = str(level)
                if key in values or any(raw == old and type(raw) is type(old) for old in raw_seen):
                    raise ConversionError("siren_volume_duplicate")
                values[key] = raw
                raw_seen.append(raw)
            config["siren_volume_values"] = values
        elif raw_type == "integer":
            raw_range = volume.get("range")
            if not isinstance(raw_range, dict) or "min" not in raw_range or "max" not in raw_range:
                raise ConversionError("siren_volume_range")
            config["siren_volume_min"] = raw_range["min"]
            config["siren_volume_max"] = raw_range["max"]
        else:
            raise ConversionError("siren_volume_mapping")
        config["siren_volume_dp"] = base._dp_id(volume)
        base._merge_membership(required, optional, volume)

    duration = dps.get("duration")
    if duration is not None:
        base._check_common_dp_semantics(duration, writable=True)
        if base._dp_type(duration) != "integer" or _raw_mapping(duration):
            raise ConversionError("siren_duration_semantics")
        # Tuya Local forwards Home Assistant's duration scalar directly to this
        # DP; unit metadata does not rescale get_values_to_set(). Keep 1:1.
        config["siren_duration_dp"] = base._dp_id(duration)
        config["siren_duration_scaling"] = 1.0
        base._merge_membership(required, optional, duration)

    for name, dp in dps.items():
        if name in functional:
            continue
        base._preserve_core_extra("siren", name, dp, config, required, optional)
    return {"platform": "siren", "config": config}, required, optional


'''
anchor = '_BINARY_SENSOR_EXTENDED_REASONS = {'
if text.count(anchor) != 1:
    raise SystemExit(f'alarm/siren insertion anchor count={text.count(anchor)}')
text = text.replace(anchor, helper + anchor, 1)
old = 'base.SUPPORTED_PLATFORMS.update({"time", "event", "water_heater"})'
new = 'base.SUPPORTED_PLATFORMS.update({"time", "event", "water_heater", "alarm_control_panel", "siren"})'
if text.count(old) != 1:
    raise SystemExit(f'platform update anchor count={text.count(old)}')
text = text.replace(old, new, 1)
old = '''base._CONVERTERS.update({
    "time": _advanced_wrapper("time", _convert_time),
    "event": _advanced_wrapper("event", _convert_event),
})'''
new = '''base._CONVERTERS.update({
    "time": _advanced_wrapper("time", _convert_time),
    "event": _advanced_wrapper("event", _convert_event),
    "alarm_control_panel": _advanced_wrapper("alarm_control_panel", _convert_alarm_control_panel_productless),
    "siren": _advanced_wrapper("siren", _convert_siren_productless),
})'''
if text.count(old) != 1:
    raise SystemExit(f'converter update anchor count={text.count(old)}')
path.write_text(text.replace(old, new, 1))

Path('tests/test_productless_alarm_siren.py').write_text(r'''"""Productless Alarm Control Panel and Siren regressions."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import import_tuya_local as base
import import_tuya_local_productless as productless


class ProductlessAlarmSirenTests(unittest.TestCase):
    def test_alarm_state_and_optional_extra(self):
        entity = {
            "entity": "alarm_control_panel",
            "dps": [
                {"id": 1, "type": "string", "name": "alarm_state", "mapping": [
                    {"dps_val": "disarmed", "value": "disarmed"},
                    {"dps_val": "arm", "value": "armed_away"},
                    {"dps_val": "home", "value": "armed_home"},
                    {"dps_val": "sos", "value": "triggered"},
                ]},
                {"id": 24, "type": "string", "name": "zone_attribute", "optional": True},
            ],
        }
        converted, required, optional = productless.base._CONVERTERS["alarm_control_panel"](entity)
        cfg = converted["config"]
        self.assertEqual(cfg["alarm_state_values"]["armed_away"], "arm")
        self.assertEqual(cfg["alarm_state_values"]["triggered"], "sos")
        self.assertEqual(cfg["extra_state_attributes_dps"]["zone_attribute"], 24)
        self.assertEqual(required, {1})
        self.assertEqual(optional, {24})

    def test_siren_tone_volume_duration(self):
        entity = {
            "entity": "siren",
            "dps": [
                {"id": 1, "name": "tone", "type": "string", "mapping": [
                    {"dps_val": "alarm_sound", "value": "sound"},
                    {"dps_val": "alarm_sound_light", "value": "sound+light", "default": True},
                    {"dps_val": "normal", "value": "off"},
                ]},
                {"id": 5, "name": "volume_level", "type": "string", "mapping": [
                    {"dps_val": "mute", "value": 0.0},
                    {"dps_val": "high", "value": 1.0},
                ]},
                {"id": 7, "name": "duration", "type": "integer", "range": {"min": 1, "max": 59}, "unit": "min"},
            ],
        }
        converted, required, optional = productless.base._CONVERTERS["siren"](entity)
        cfg = converted["config"]
        self.assertEqual(cfg["siren_default_tone"], "sound+light")
        self.assertEqual(cfg["siren_tone_values"]["off"], "normal")
        self.assertEqual(cfg["siren_volume_values"]["1.0"], "high")
        self.assertEqual(cfg["siren_duration_scaling"], 1.0)
        self.assertEqual(required, {1, 5, 7})
        self.assertEqual(optional, set())

    def test_alarm_unknown_friendly_fails_closed(self):
        entity = {"entity": "alarm_control_panel", "dps": [{"id": 1, "type": "string", "name": "alarm_state", "mapping": [{"dps_val": "x", "value": "mystery"}]}]}
        with self.assertRaisesRegex(base.ConversionError, "alarm_state_mapping"):
            productless.base._CONVERTERS["alarm_control_panel"](entity)


if __name__ == "__main__":
    unittest.main()
''')
