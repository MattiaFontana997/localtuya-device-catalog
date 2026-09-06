"""Tests for newer runtime converters used by productless fingerprints."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from import_tuya_local_productless import ConversionError, convert_profile  # noqa: E402


class ProductlessExtendedConverterTests(unittest.TestCase):
    def _convert(self, entities):
        return convert_profile(
            {
                "name": "Test",
                "products": [{"id": "synthetic"}],
                "entities": entities,
            },
            source_file="test.yaml",
        )

    def test_second_only_time_preserves_total_seconds_semantics(self):
        result = self._convert([
            {
                "entity": "time",
                "dps": [
                    {
                        "id": 9,
                        "name": "second",
                        "type": "integer",
                        "range": {"min": 0, "max": 86400},
                    }
                ],
            }
        ])
        config = result["entities"][0]["config"]
        self.assertEqual(config["id"], 9)
        self.assertEqual(config["time_second_dp"], 9)
        self.assertEqual(result["match"]["required_dps"], [9])

    def test_split_time_keeps_all_component_dps(self):
        result = self._convert([
            {
                "entity": "time",
                "dps": [
                    {"id": 1, "name": "hour", "type": "integer"},
                    {"id": 2, "name": "minute", "type": "integer"},
                    {"id": 3, "name": "second", "type": "integer", "optional": True},
                ],
            }
        ])
        config = result["entities"][0]["config"]
        self.assertEqual(config["time_hour_dp"], 1)
        self.assertEqual(config["time_minute_dp"], 2)
        self.assertEqual(config["time_second_dp"], 3)
        self.assertEqual(result["match"]["required_dps"], [1, 2])
        self.assertEqual(result["match"]["optional_dps"], [3])

    def test_time_extra_dp_is_preserved_as_raw_attribute(self):
        result = self._convert([
            {
                "entity": "time",
                "dps": [
                    {"id": 9, "name": "second", "type": "integer"},
                    {"id": 42, "name": "cycle_time", "type": "string"},
                ],
            }
        ])
        config = result["entities"][0]["config"]
        self.assertEqual(config["extra_state_attributes_dps"], {"cycle_time": 42})
        self.assertEqual(result["match"]["required_dps"], [9, 42])

    def test_hms_time_stays_fail_closed(self):
        with self.assertRaisesRegex(ConversionError, "time_hms_not_lossless"):
            self._convert([
                {
                    "entity": "time",
                    "dps": [{"id": 1, "name": "hms", "type": "string"}],
                }
            ])

    def test_static_event_mapping_converts_exact_raw_values(self):
        result = self._convert([
            {
                "entity": "event",
                "dps": [
                    {
                        "id": 14,
                        "name": "event",
                        "type": "string",
                        "mapping": [
                            {"dps_val": "loweralarm", "value": "low"},
                            {"dps_val": "upperalarm", "value": "high"},
                            {"dps_val": "cancel", "value": "normal"},
                        ],
                    }
                ],
            }
        ])
        config = result["entities"][0]["config"]
        self.assertEqual(config["event_dp"], 14)
        self.assertEqual(
            config["event_types"],
            {"low": "loweralarm", "high": "upperalarm", "normal": "cancel"},
        )

    def test_event_default_rule_without_exact_raw_value_is_rejected(self):
        with self.assertRaisesRegex(ConversionError, "event_mapping"):
            self._convert([
                {
                    "entity": "event",
                    "dps": [
                        {
                            "id": 14,
                            "name": "event",
                            "type": "string",
                            "mapping": [{"value": "alarm"}],
                        }
                    ],
                }
            ])

    def test_advanced_constraint_redirect_resolves_names_to_dp_ids(self):
        result = self._convert([
            {
                "entity": "sensor",
                "dps": [
                    {
                        "id": 1,
                        "name": "sensor",
                        "type": "integer",
                        "readonly": True,
                        "mapping": [
                            {
                                "constraint": "unit",
                                "conditions": [
                                    {"dps_val": "f", "value_redirect": "sensor_f"},
                                    {"dps_val": "c"},
                                ],
                            }
                        ],
                    },
                    {"id": 2, "name": "unit", "type": "string", "readonly": True, "hidden": True},
                    {"id": 3, "name": "sensor_f", "type": "integer", "readonly": True, "hidden": True},
                ],
            }
        ])
        config = result["entities"][0]["config"]
        self.assertEqual(
            config["advanced_mapping_by_dp"],
            {
                "1": [
                    {
                        "constraint_dp": 2,
                        "conditions": [
                            {"dps_val": "f", "value_redirect_dp": 3},
                            {"dps_val": "c"},
                        ],
                    }
                ]
            },
        )
        self.assertEqual(result["match"]["required_dps"], [1, 2, 3])

    def test_advanced_condition_can_set_external_constraint(self):
        result = self._convert([
            {
                "entity": "switch",
                "dps": [
                    {
                        "id": 1,
                        "name": "switch",
                        "type": "boolean",
                        "mapping": [
                            {
                                "constraint": "mode",
                                "conditions": [
                                    {"dps_val": "enabled", "value": True},
                                    {"dps_val": "disabled", "value": False},
                                ],
                            }
                        ],
                    },
                    {"id": 2, "name": "mode", "type": "string", "hidden": True},
                ],
            }
        ])
        config = result["entities"][0]["config"]
        self.assertEqual(config["advanced_mapping_by_dp"]["1"][0]["constraint_dp"], 2)
        self.assertEqual(
            config["advanced_mapping_by_dp"]["1"][0]["conditions"],
            [
                {"dps_val": "enabled", "value": True},
                {"dps_val": "disabled", "value": False},
            ],
        )
        self.assertEqual(result["match"]["required_dps"], [1, 2])

    def test_advanced_value_mirror_stays_fail_closed(self):
        with self.assertRaisesRegex(ConversionError, "advanced_mapping_unsupported:value_mirror"):
            self._convert([
                {
                    "entity": "sensor",
                    "dps": [
                        {
                            "id": 1,
                            "name": "sensor",
                            "type": "integer",
                            "mapping": [{"value_mirror": "other"}],
                        },
                        {"id": 2, "name": "other", "type": "integer"},
                    ],
                }
            ])

    def test_advanced_missing_constraint_reference_stays_fail_closed(self):
        with self.assertRaisesRegex(ConversionError, "advanced_mapping_constraint_missing:unit"):
            self._convert([
                {
                    "entity": "sensor",
                    "dps": [
                        {
                            "id": 1,
                            "name": "sensor",
                            "type": "integer",
                            "mapping": [
                                {
                                    "constraint": "unit",
                                    "conditions": [{"dps_val": "f", "value": 1}],
                                }
                            ],
                        }
                    ],
                }
            ])

    def test_writable_redirect_with_target_mapping_stays_fail_closed(self):
        with self.assertRaisesRegex(ConversionError, "advanced_mapping_redirect_target_mapping"):
            self._convert([
                {
                    "entity": "number",
                    "dps": [
                        {
                            "id": 1,
                            "name": "value",
                            "type": "integer",
                            "range": {"min": 0, "max": 100},
                            "mapping": [
                                {
                                    "constraint": "unit",
                                    "conditions": [
                                        {"dps_val": "f", "value_redirect": "value_f"}
                                    ],
                                }
                            ],
                        },
                        {"id": 2, "name": "unit", "type": "string", "hidden": True},
                        {
                            "id": 3,
                            "name": "value_f",
                            "type": "integer",
                            "hidden": True,
                            "range": {"min": 32, "max": 212},
                            "mapping": [{"scale": 10}],
                        },
                    ],
                }
            ])

    def test_dynamic_condition_scale_stays_fail_closed(self):
        with self.assertRaisesRegex(ConversionError, "advanced_mapping_condition_semantics"):
            self._convert([
                {
                    "entity": "sensor",
                    "dps": [
                        {
                            "id": 1,
                            "name": "sensor",
                            "type": "integer",
                            "mapping": [
                                {
                                    "constraint": "unit",
                                    "conditions": [{"dps_val": "f", "scale": 10}],
                                }
                            ],
                        },
                        {"id": 2, "name": "unit", "type": "string", "hidden": True},
                    ],
                }
            ])


    def test_conditioned_boolean_hvac_projects_full_ha_mode_domain(self):
        result = self._convert([
            {
                "entity": "climate",
                "dps": [
                    {
                        "id": 1,
                        "name": "hvac_mode",
                        "type": "boolean",
                        "mapping": [
                            {"dps_val": False, "value": "off"},
                            {
                                "dps_val": True,
                                "constraint": "mode",
                                "conditions": [
                                    {"dps_val": "manual", "value": "heat"},
                                    {"dps_val": "auto", "value": "auto"},
                                ],
                            },
                        ],
                    },
                    {"id": 4, "name": "mode", "type": "string", "hidden": True},
                ],
            }
        ])
        config = result["entities"][0]["config"]
        self.assertEqual(
            config["hvac_mode_values"],
            {"off": "off", "heat": "heat", "auto": "auto"},
        )
        self.assertEqual(
            config["advanced_mapping_by_dp"]["1"],
            [
                {"dps_val": False, "value": "off"},
                {
                    "dps_val": True,
                    "constraint_dp": 4,
                    "conditions": [
                        {"dps_val": "manual", "value": "heat"},
                        {"dps_val": "auto", "value": "auto"},
                    ],
                },
            ],
        )
        self.assertEqual(result["match"]["required_dps"], [1, 4])


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


if __name__ == "__main__":
    unittest.main()
