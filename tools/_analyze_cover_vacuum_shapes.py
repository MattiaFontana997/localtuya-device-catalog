from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import yaml

root = Path('upstream-tuya-local/custom_components/tuya_local/devices')
for platform in ('cover', 'vacuum'):
    profiles = 0
    entities_count = 0
    productless = 0
    combos = Counter()
    names = Counter()
    types = defaultdict(Counter)
    keysets = defaultdict(Counter)
    mappings = defaultdict(Counter)
    examples = defaultdict(list)
    for path in sorted(root.glob('*.yaml')):
        try:
            doc = yaml.safe_load(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        if not isinstance(doc, dict) or not isinstance(doc.get('entities'), list):
            continue
        entities = [e for e in doc['entities'] if isinstance(e, dict) and e.get('entity') == platform]
        if not entities:
            continue
        profiles += 1
        products = doc.get('products')
        if not isinstance(products, list) or not any(isinstance(p, dict) and p.get('id') for p in products):
            productless += 1
        for entity in entities:
            entities_count += 1
            dps = entity.get('dps')
            if not isinstance(dps, list):
                combos[('<missing>',)] += 1
                continue
            combo = []
            for dp in dps:
                if not isinstance(dp, dict):
                    continue
                name = str(dp.get('name'))
                combo.append(name)
                names[name] += 1
                types[name][str(dp.get('type'))] += 1
                keysets[name][','.join(sorted(dp.keys()))] += 1
                mapping = dp.get('mapping')
                if isinstance(mapping, list):
                    for rule in mapping:
                        if isinstance(rule, dict):
                            mappings[name][','.join(sorted(rule.keys()))] += 1
                key = (name, str(dp.get('type')), ','.join(sorted(dp.keys())))
                if len(examples[key]) < 4:
                    examples[key].append(path.name)
            combos[tuple(combo)] += 1
    print(f'## {platform.upper()}')
    print('PROFILES', profiles, 'ENTITIES', entities_count, 'PRODUCTLESS', productless)
    print('TOP_COMBOS')
    for combo, count in combos.most_common(30):
        print(count, '|', ','.join(combo))
    print('NAMES')
    for name, count in names.most_common():
        print(name, count, dict(types[name]))
    print('MAPPING_SHAPES')
    for name in names:
        if mappings[name]:
            print(name, dict(mappings[name]))
    print('KEYSETS')
    for name in names:
        print(name, dict(keysets[name]))
    print('EXAMPLES')
    for key, files in sorted(examples.items()):
        print(key, '=>', ','.join(files))
