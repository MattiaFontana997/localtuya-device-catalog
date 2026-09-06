import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from import_tuya_local_productless import ConversionError, convert_profile


def _convert(dp, *, entity_extra=None):
    entity = {"entity": "binary_sensor", "dps": [dp]}
    if entity_extra:
        entity.update(entity_extra)
    profile = {
        "name": "Batch H test",
        "products": [{"id": "batch-h-test"}],
        "entities": [entity],
    }
    return convert_profile(profile, source_file="batch_h_test.yaml")


def test_bitfield_mask_mapping_uses_extended_runtime_grammar():
    result = _convert({
        "id": 19,
        "type": "bitfield",
        "name": "sensor",
        "mapping": [
            {"dps_val": 4, "value": True},
            {"value": False},
        ],
    })
    config = result["entities"][0]["config"]
    assert config["binary_sensor_bitfield"] is True
    assert config["binary_sensor_mapping"] == [
        {"dps_val": 4, "value": True},
        {"value": False},
    ]


def test_bitfield_problem_mapping_preserves_ordered_catch_all():
    result = _convert({
        "id": 9,
        "type": "bitfield",
        "name": "sensor",
        "mapping": [
            {"dps_val": 0, "value": False},
            {"dps_val": 1, "value": False},
            {"dps_val": 2, "value": False},
            {"value": True},
        ],
    })
    assert result["entities"][0]["config"]["binary_sensor_mapping"][-1] == {"value": True}


def test_integer_default_mapping_is_lossless():
    result = _convert({
        "id": 1,
        "type": "integer",
        "name": "sensor",
        "mapping": [
            {"dps_val": 1, "value": True},
            {"value": False},
        ],
    })
    config = result["entities"][0]["config"]
    assert "binary_sensor_bitfield" not in config
    assert config["binary_sensor_mapping"][1] == {"value": False}


def test_string_multiple_true_values_are_preserved():
    result = _convert({
        "id": 1,
        "type": "string",
        "name": "sensor",
        "mapping": [
            {"dps_val": "small_move", "value": True},
            {"dps_val": "large_move", "value": True},
            {"value": False},
        ],
    })
    config = result["entities"][0]["config"]
    assert len(config["binary_sensor_mapping"]) == 3


def test_existing_exact_mapping_keeps_legacy_output():
    result = _convert({
        "id": 25,
        "type": "string",
        "name": "sensor",
        "mapping": [
            {"dps_val": "on", "value": True},
            {"dps_val": "off", "value": False},
        ],
    })
    config = result["entities"][0]["config"]
    assert config["state_on"] == "on"
    assert config["state_off"] == "off"
    assert "binary_sensor_mapping" not in config


def test_null_bitfield_rule_is_preserved_exactly():
    result = _convert({
        "id": 19,
        "type": "bitfield",
        "name": "sensor",
        "mapping": [
            {"dps_val": 0, "value": False},
            {"dps_val": None, "value": False},
            {"value": True},
        ],
    })
    assert result["entities"][0]["config"]["binary_sensor_mapping"][1]["dps_val"] is None


def test_non_boolean_output_stays_fail_closed():
    try:
        _convert({
            "id": 1,
            "type": "integer",
            "name": "sensor",
            "mapping": [
                {"dps_val": 1, "value": "alarm"},
                {"value": False},
            ],
        })
    except ConversionError as err:
        assert str(err) == "binary_sensor_non_boolean_mapping"
    else:
        raise AssertionError("expected ConversionError")
