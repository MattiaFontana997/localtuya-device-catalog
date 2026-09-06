from pathlib import Path

path = Path('tests/test_import_tuya_local_productless.py')
text = path.read_text(encoding='utf-8')
marker = '\n\nif __name__ == "__main__":\n'
if marker not in text:
    raise SystemExit('test module marker not found')
method = r'''
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
'''
if 'test_conditioned_boolean_hvac_projects_full_ha_mode_domain' in text:
    raise SystemExit('projection test already present')
path.write_text(text.replace(marker, '\n' + method + marker), encoding='utf-8')
