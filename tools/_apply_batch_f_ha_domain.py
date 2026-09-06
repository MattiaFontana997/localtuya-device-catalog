from pathlib import Path
import re

path = Path('tools/import_tuya_local_productless.py')
text = path.read_text(encoding='utf-8')

pattern = re.compile(
    r'(    writable_source = dp\.get\("readonly"\) is not True\n)\n'
    r'    for source in rules:\n'
    r'        if not \(set\(source\) & \(_ADVANCED_SOURCE_KEYS \| _UNSUPPORTED_ADVANCED_KEYS\)\):\n'
    r'            continue\n'
)
text, n = pattern.subn(
    r'\1    transform_keys = {"scale", "invert", "step", "range", "target_range"}\n\n'
    r'    for source in rules:\n',
    text,
    count=1,
)
if n != 1:
    raise SystemExit(f'translator loop substitutions={n}')

pattern = re.compile(
    r'(        if set\(source\) - allowed_source:\n'
    r'            raise ConversionError\("advanced_mapping_rule_semantics"\)\n)\n'
    r'        rule: dict\[str, Any\] = \{\}\n'
)
text, n = pattern.subn(
    r'\1        if set(source) & transform_keys:\n'
    r'            raise ConversionError("advanced_mapping_rule_transform_semantics")\n\n'
    r'        rule: dict[str, Any] = {}\n',
    text,
    count=1,
)
if n != 1:
    raise SystemExit(f'allowed block substitutions={n}')

start = text.index('def _project_mapping_for_base(')
end = text.index('\n\ndef _validate_consumed_dependency', start)
new_func = '''def _project_mapping_for_base(dp: dict[str, Any]) -> dict[str, Any]:
    """Project an advanced-mapped raw DP into its HA-facing value domain."""
    projected = copy.deepcopy(dp)
    rules = _raw_mapping(dp)
    outputs: list[Any] = []
    missing = object()

    def add_output(value: Any) -> None:
        if value is missing:
            raise ConversionError("advanced_mapping_unbounded_output")
        value = _runtime_scalar(value, "advanced_mapping_projection_scalar")
        if value is None:
            raise ConversionError("advanced_mapping_projection_none")
        if not any(value == seen and type(value) is type(seen) for seen in outputs):
            outputs.append(value)

    for source in rules:
        if source.get("invalid") is True or source.get("hidden") is True:
            continue
        conditions = source.get("conditions")
        if isinstance(conditions, list) and conditions:
            for condition in conditions:
                if not isinstance(condition, dict):
                    raise ConversionError("advanced_mapping_condition")
                if condition.get("invalid") is True or condition.get("hidden") is True:
                    continue
                add_output(condition.get(
                    "value", source.get("value", source.get("dps_val", missing))
                ))
        else:
            add_output(source.get("value", source.get("dps_val", missing)))

    if not outputs:
        raise ConversionError("advanced_mapping_empty_projection")
    kinds = {bool if isinstance(v, bool) else type(v) for v in outputs}
    if len(kinds) != 1:
        raise ConversionError("advanced_mapping_mixed_output_types")
    kind = next(iter(kinds))
    if kind is str:
        projected["type"] = "string"
    elif kind is bool:
        projected["type"] = "boolean"
    elif kind is int:
        projected["type"] = "integer"
    else:
        raise ConversionError("advanced_mapping_projection_type")
    projected["mapping"] = [
        {"dps_val": value, "value": value} for value in outputs
    ]
    return projected
'''
text = text[:start] + new_func + text[end:]
path.write_text(text, encoding='utf-8')
