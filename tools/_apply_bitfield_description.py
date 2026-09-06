from pathlib import Path

path = Path("tools/import_tuya_local_productless.py")
text = path.read_text(encoding="utf-8")

old_type_gate = '''    if dp_type not in {"boolean", "integer", "string"}:\n        raise ConversionError(f"{platform}_mapped_extra_type:{name}")\n\n    translated: list[dict[str, Any]] = []\n'''
new_type_gate = '''    if dp_type == "bitfield":\n        translated: list[dict[str, Any]] = []\n        seen_raw: set[int] = set()\n        for rule in rules:\n            if set(rule) != {"dps_val", "value"}:\n                raise ConversionError(f"{platform}_mapped_extra_mapping:{name}")\n            raw = rule.get("dps_val")\n            if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:\n                raise ConversionError(f"{platform}_mapped_extra_raw_type:{name}")\n            if raw in seen_raw:\n                raise ConversionError(f"{platform}_mapped_extra_duplicate_raw:{name}")\n            seen_raw.add(raw)\n            translated.append({\n                "dps_val": raw,\n                "value": _runtime_scalar(\n                    rule.get("value"), f"{platform}_mapped_extra_scalar:{name}"\n                ),\n                "bitmask": True,\n            })\n        return translated\n\n    if dp_type not in {"boolean", "integer", "string"}:\n        raise ConversionError(f"{platform}_mapped_extra_type:{name}")\n\n    translated: list[dict[str, Any]] = []\n'''
if new_type_gate not in text:
    if old_type_gate not in text:
        raise SystemExit("mapped extra type gate anchor missing")
    text = text.replace(old_type_gate, new_type_gate, 1)

old_store = '''    """Expose one extra attribute through dps() instead of the raw status cache."""\n    dp_id = base._dp_id(dp)\n    key = str(dp_id)\n    existing = advanced_by_dp.get(key)\n    if existing is not None and existing != rules:\n        raise ConversionError(f"{platform}_mapped_extra_dp_conflict:{name}")\n    advanced_by_dp[key] = copy.deepcopy(rules)\n\n    raw_attrs = config.get("extra_state_attributes_dps", {})\n    mapped_attrs = config.setdefault("mapped_extra_state_attributes_dps", {})\n    if name in raw_attrs or name in mapped_attrs:\n        raise ConversionError(f"{platform}_mapped_extra_name_conflict:{name}")\n    if name not in {"state", "available"}:\n        if len(raw_attrs) + len(mapped_attrs) >= 32:\n            raise ConversionError("multi_dp_too_many_extra_attributes")\n        mapped_attrs[name] = dp_id\n    if not mapped_attrs:\n        config.pop("mapped_extra_state_attributes_dps", None)\n    base._merge_membership(required, optional, dp)\n'''
new_store = '''    """Expose one extra attribute with mapping scoped only to that attribute."""\n    dp_id = base._dp_id(dp)\n\n    raw_attrs = config.get("extra_state_attributes_dps", {})\n    mapped_attrs = config.setdefault("mapped_extra_state_attributes_dps", {})\n    scoped = config.setdefault("mapped_extra_state_attribute_mappings", {})\n    if name in raw_attrs or name in mapped_attrs or name in scoped:\n        raise ConversionError(f"{platform}_mapped_extra_name_conflict:{name}")\n    if name not in {"state", "available"}:\n        if len(raw_attrs) + len(mapped_attrs) >= 32:\n            raise ConversionError("multi_dp_too_many_extra_attributes")\n        mapped_attrs[name] = dp_id\n        scoped[name] = copy.deepcopy(rules)\n    if not mapped_attrs:\n        config.pop("mapped_extra_state_attributes_dps", None)\n    if not scoped:\n        config.pop("mapped_extra_state_attribute_mappings", None)\n    base._merge_membership(required, optional, dp)\n'''
if new_store not in text:
    if old_store not in text:
        raise SystemExit("mapped extra store anchor missing")
    text = text.replace(old_store, new_store, 1)

path.write_text(text, encoding="utf-8")

# Permanent regressions in the extended productless suite.
test_path = Path("tests/test_import_tuya_local_productless.py")
test = test_path.read_text(encoding="utf-8")
old_expect = '''        self.assertEqual(config["mapped_extra_state_attributes_dps"], {"description": 2})\n        self.assertEqual(\n            config["advanced_mapping_by_dp"]["2"],\n            [{"dps_val": "x", "value": "friendly"}],\n        )\n'''
new_expect = '''        self.assertEqual(config["mapped_extra_state_attributes_dps"], {"description": 2})\n        self.assertEqual(\n            config["mapped_extra_state_attribute_mappings"]["description"],\n            [{"dps_val": "x", "value": "friendly"}],\n        )\n        self.assertNotIn("advanced_mapping_by_dp", config)\n'''
if new_expect not in test:
    if old_expect not in test:
        raise SystemExit("mapped extra test expectation anchor missing")
    test = test.replace(old_expect, new_expect, 1)

method = '''\n    def test_multidp_bitfield_description_uses_scoped_ordered_bitmask_mapping(self):\n        result = self._convert([\n            {\n                "entity": "binary_sensor",\n                "dps": [\n                    {\n                        "id": 19,\n                        "name": "sensor",\n                        "type": "bitfield",\n                        "mapping": [\n                            {"dps_val": 0, "value": False},\n                            {"value": True},\n                        ],\n                    },\n                    {"id": 19, "name": "fault_code", "type": "bitfield"},\n                    {\n                        "id": 19,\n                        "name": "description",\n                        "type": "bitfield",\n                        "mapping": [\n                            {"dps_val": 0, "value": "OK"},\n                            {"dps_val": 1, "value": "Fault A"},\n                            {"dps_val": 2, "value": "Fault B"},\n                            {"dps_val": 4, "value": "Fault C"},\n                        ],\n                    },\n                ],\n            }\n        ])\n        config = result["entities"][0]["config"]\n        self.assertTrue(config["binary_sensor_bitfield"])\n        self.assertEqual(config["extra_state_attributes_dps"], {"fault_code": 19})\n        self.assertEqual(\n            config["mapped_extra_state_attributes_dps"], {"description": 19}\n        )\n        self.assertEqual(\n            config["mapped_extra_state_attribute_mappings"]["description"],\n            [\n                {"dps_val": 0, "value": "OK", "bitmask": True},\n                {"dps_val": 1, "value": "Fault A", "bitmask": True},\n                {"dps_val": 2, "value": "Fault B", "bitmask": True},\n                {"dps_val": 4, "value": "Fault C", "bitmask": True},\n            ],\n        )\n        self.assertNotIn("advanced_mapping_by_dp", config)\n        self.assertEqual(result["match"]["required_dps"], [19])\n\n    def test_multidp_bitfield_description_rejects_default_rule(self):\n        with self.assertRaisesRegex(ConversionError, "multi_dp_mapped_extra:description"):\n            self._convert([\n                {\n                    "entity": "binary_sensor",\n                    "dps": [\n                        {"id": 19, "name": "sensor", "type": "bitfield",\n                         "mapping": [{"dps_val": 0, "value": False}, {"value": True}]},\n                        {"id": 19, "name": "fault_code", "type": "bitfield"},\n                        {"id": 19, "name": "description", "type": "bitfield",\n                         "mapping": [{"dps_val": 0, "value": "OK"}, {"value": "Other"}]},\n                    ],\n                }\n            ])\n'''
if 'test_multidp_bitfield_description_uses_scoped_ordered_bitmask_mapping' not in test:
    marker = '\n    def test_multidp_richer_extra_mapping_stays_fail_closed(self):\n'
    idx = test.find(marker)
    if idx < 0:
        raise SystemExit("bitfield test insertion anchor missing")
    test = test[:idx] + method + test[idx:]
test_path.write_text(test, encoding="utf-8")

# Update the dedicated mapped-extra regression to the new scoped contract.
mapped_test_path = Path("tests/test_productless_mapped_extras.py")
mapped_test = mapped_test_path.read_text(encoding="utf-8")
old_mapped_expect = '''        self.assertEqual(config["mapped_extra_state_attributes_dps"], {"unit": 23})\n        self.assertNotIn("extra_state_attributes_dps", config)\n        self.assertEqual(advanced["23"], [\n            {"dps_val": "c", "value": "C"},\n            {"dps_val": "f", "value": "F"},\n        ])\n        self.assertIn(23, required)\n'''
new_mapped_expect = '''        self.assertEqual(config["mapped_extra_state_attributes_dps"], {"unit": 23})\n        self.assertNotIn("extra_state_attributes_dps", config)\n        self.assertEqual(config["mapped_extra_state_attribute_mappings"]["unit"], [\n            {"dps_val": "c", "value": "C"},\n            {"dps_val": "f", "value": "F"},\n        ])\n        self.assertEqual(advanced, {})\n        self.assertIn(23, required)\n'''
if new_mapped_expect not in mapped_test:
    if old_mapped_expect not in mapped_test:
        raise SystemExit("dedicated mapped-extra test anchor missing")
    mapped_test = mapped_test.replace(old_mapped_expect, new_mapped_expect, 1)
mapped_test_path.write_text(mapped_test, encoding="utf-8")

print("bitfield description importer patch applied")
