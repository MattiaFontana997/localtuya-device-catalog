# Productless development (develop only)

Pinned upstream: `38347807cfc81ae8789974d98532eb928f42f174` (1737 profiles; 211 productless).

| Batch | Candidates | Safe fingerprints | Blocked by builder | Total catalog |
| --- | ---: | ---: | ---: | ---: |
| I | 98 | 75 | 23 | 77 |
| J | 102 | 79 | 23 | 81 |

Counts come from the complete importer and global optional-DP collision builder. Imported fingerprints remain experimental. Stable branches and releases are untouched.

## Batch I closure

Removed all Batch I apply/inspection helpers. Kept the read-only generic gap inspection workflow for subsequent batches. Enabled catalog validation on develop pushes and PRs. Runtime tests, HACS and Hassfest passed at 282a4be; catalog validation and gap inspection passed at 6bfc4da.

## Batch J: real shapes and exact sensor reads

The original non_uniform_numeric_mapping label grouped text enums with numeric enums. Added a bounded, read-only sensor_value_mapping grammar: raw-specific values, ordered fallback, null matching, positive finite scale, inversion over a declared range, static range projection and mapping icons. Raw strings match using Tuya Local's string comparison. Conversion order is inversion, projection, division, with no legacy two-decimal rounding. Scale and icon selection use the original device value before numeric-string coercion. No expressions, templates, callbacks, dynamic conditions, offsets or arbitrary calculations are accepted.

Runtime and catalog copies of sensor_mapping.py have identical content. The catalog schema and semantic validator reject unsupported grammar and double transforms.

| Original blocker profile | Result after J |
| --- | --- |
| illumanance_sensor | Convertible |
| illumanance_v2_sensor | Convertible |
| pgst_climate_sensor | Convertible |
| wetair_wawh1210lw_humidifier | Convertible, including value-specific icons |
| ampbolt_portable_evcharger | Still blocked: advanced rule transforms / encoded dependencies |
| digma_disenseg1_gassensor | Still blocked: mapped binary-sensor description attribute |
| inkbird_iaqm129w_airqualitymonitor | Still blocked: dynamic sensor unit |
| wouej_evcharger | Still blocked: non-boolean switch |

Validated 327 value comparisons against TuyaDpsConfig from the pinned upstream, including null, unknown raw values, numeric strings and every raw enum member in generated mappings. All 81 catalog mappings are accepted by the development runtime.

The existing H/I function-style tests were not collected by unittest. Added explicit load_tests hooks so their 14 regressions now run in the unchanged CI runner.

K–P remain in progress. Media player remains excluded. No release is ready.
## Batch K — exact fan mappings

- Generated candidates: **111**
- Safe productless fingerprints: **82**
- Blocked after global collision analysis: **29**
- Catalog mappings including Product-ID mappings: **84**
- Adds bounded exact enumerated fan speed mappings with closest-value writes, ordered oscillation exact/default mappings, typed preset raw values, optional presets, and safe raw fan extras.
- Switchless fans and non-HA direction states remain fail-closed.
- Stable branches remain untouched.
## Batch L — Water Heater

- Generated candidates: **115**
- Safe productless fingerprints: **84**
- Blocked after global collision analysis: **31**
- Catalog mappings including Product-ID mappings: **86**
- Adds lossless productless Water Heater conversion for bounded static/advanced mode, temperature, away-mode and raw-extra semantics.
- Dynamic Celsius/Fahrenheit condition-range redirects remain fail-closed.
- Stable branches remain untouched.
## Batch M — Advanced Mapping metadata

- Converter candidates: **118**
- Remaining skipped productless profiles: **93**
- Safe productless fingerprints: **87**
- Blocked after global collision analysis: **31**
- Catalog mappings including Product-ID mappings: **89**
- Adds lossless conditional range/step metadata for Climate/Number and preserves static base transforms without double application.
- Fixes enum projection when advanced conditions are invalid/hidden-only.
- Condition scale, nested mappings, transformed redirect targets and unsupported recursive writes remain fail-closed.
- Stable branches remain untouched.
