# Tuya Local import analysis

LocalTuya's community catalog can reuse publicly available device knowledge
from compatible open-source projects when licensing and attribution are
preserved and the imported behaviour can be represented safely.

The first supported source-analysis workflow targets:

- source: `make-all/tuya-local`
- source license: MIT
- target: LocalTuya Device Catalog schema v1

No source profile is published automatically by the analyzer.

## Why analyze before importing

Tuya Local device YAML files can describe behaviour that LocalTuya catalog
schema v1 does not model explicitly, including:

- multiple product IDs for one profile
- optional datapoints
- forced datapoint refreshes
- persistence behaviour
- hidden/internal datapoints
- conditional mappings
- read-only/sensitive datapoint metadata
- encoded datapoint types
- Home Assistant platforms not yet supported by the LocalTuya catalog

Silently dropping any of those semantics could create a mapping that validates
but behaves incorrectly on real hardware.

For that reason, the analyzer is deliberately conservative.

## Running the analyzer

Clone `make-all/tuya-local` next to this repository, then run:

```bash
python -m pip install "PyYAML>=6,<7"
python tools/analyze_tuya_local.py ../tuya-local
```

To save the complete machine-readable report:

```bash
python tools/analyze_tuya_local.py ../tuya-local --json tuya-local-report.json
```

The source argument can also point directly at:

```text
custom_components/tuya_local/devices
```

## Status values

### `convertible_v1`

The source profile uses only a conservative subset that can be represented by
catalog schema v1 without known semantic loss.

This status means "eligible for converter work", not "safe to publish without
review".

### `needs_v2`

The profile uses one or more features that should first be represented by a
future catalog schema version or explicit LocalTuya behaviour.

### `unsupported_platform`

The profile uses a Home Assistant platform that the current LocalTuya catalog
does not support.

### `invalid`

The analyzer could not identify the minimum product/entity/datapoint structure
needed for a product-specific LocalTuya mapping.

## Trust and promotion rules

Imported mappings must never be promoted directly to `verified`.

The intended lifecycle is:

```text
source profile
    -> analyzer
    -> converter
    -> experimental submission
    -> review
    -> community
    -> physical hardware validation
    -> verified
```

A source project's existing device support is useful evidence, but it is not a
substitute for LocalTuya physical verification.

## Attribution

Any generated mapping derived from Tuya Local data must retain machine-readable
source provenance once catalog schema support for provenance is introduced.
Repository-level attribution is maintained in `THIRD_PARTY_NOTICES.md`.

The analyzer itself does not copy Tuya Local source files into this repository.
