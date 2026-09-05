# LocalTuya Device Catalog

Community-maintained device mapping catalog for the
[LocalTuya fork](https://github.com/MattiaFontana997/localtuya).

The catalog preserves product-specific Tuya mappings that have been observed
and reviewed on real devices, without requiring a new LocalTuya release for
every newly supported product.

## What belongs in the catalog

The catalog is intentionally product-specific.

A catalog entry must use one or more real Tuya product IDs and should only be
added when there is useful device-specific knowledge that the generic LocalTuya
mapper cannot safely infer by itself.

Generic Tuya switches, lights, covers, fans, thermostats, sensors, numbers and
selects should remain handled by LocalTuya's built-in metadata mapper whenever
possible.

See [`docs/known-device-coverage.md`](docs/known-device-coverage.md) for the
current product-specific inventory and generic LocalTuya coverage.

## How LocalTuya uses the catalog

LocalTuya first builds entities from its built-in generic mapper.
Product-specific catalog mappings can then complete or refine that result.

Schema V2 matches a mapping against:

- one of the mapping's Tuya `product_ids`
- Tuya category, when available
- all `required_dps` detected from the device over the LAN

`optional_dps` may add entities or capabilities when present, but their absence
does not reject an otherwise compatible mapping.

LocalTuya can use:

- the current remote `catalog.json`
- a persistent local cache
- a bundled `builtin_catalog.json` snapshot as an offline fallback

A remote mapping is never trusted only because its product ID matches.
Required datapoints must also be present on the actual local device.

## Schema V2

Catalog V2 adds three features required for safely sharing mappings across
firmware and product variants:

### Product aliases

A single mapping can describe several Tuya product IDs when they share the same
behaviour:

```json
"product_ids": ["product-a", "product-b"]
```

Product IDs are sorted and deduplicated by repository tooling.

### Required and optional datapoints

`required_dps` are fingerprint anchors: every required DP must be observed for
the mapping to match.

`optional_dps` describe capabilities that may exist only on some firmware or
product variants. Missing optional primary DPS cause only the affected entity
to be skipped; missing optional secondary DPS remove only the capability backed
by that DP.

A DP cannot be both required and optional.

### Provenance

Mappings derived from another open-source device knowledge base can carry
non-executable attribution metadata:

```json
"provenance": {
  "source": "make-all/tuya-local",
  "path": "custom_components/tuya_local/devices/example.yaml",
  "revision": "<upstream commit>",
  "license": "MIT"
}
```

Provenance never changes runtime matching or trust. Imported mappings still
start as `experimental`.

## Confidence levels

Catalog entries use one of three confidence levels:

- `experimental` — newly submitted or imported mapping awaiting trusted review
- `community` — reviewed mapping accepted into the published catalog
- `verified` — community mapping additionally verified on real hardware

The repository enforces:

`experimental` → `community` → `verified`

An experimental submission cannot be promoted directly to `verified`.
Promotion to `community` moves the accepted mapping from `submissions/` into
`catalog.json`. Promotion to `verified` is allowed only after the mapping is
already `community` and requires an explicit physical verification note.

Do not mark a mapping as `verified` only because its JSON validates or because
another project supports the same product. Entity behaviour must have been
tested on physical hardware with LocalTuya.

## Current real product mappings

### LSC Smart Connect RGB+CCT smart light (Action)

- Brand: **LSC Smart Connect**
- Retailer: **Action**
- Tuya product ID: `r7sn2fda7l5hwzvx`
- Tuya category: `dj`
- Mapping ID: `r7sn2fda7l5hwzvx-0cc115f608`
- Platform: `light`
- Protocol physically tested: **Tuya 3.5**
- Required DPS: 20, 21, 22, 23, 24

Power, brightness, color temperature, color and spontaneous device/Tuya app
state updates back to Home Assistant have been tested on real hardware.

### EMOS GoSmart P56201 Wi-Fi Room Thermostat

- Brand: **EMOS**
- Product: **GoSmart P56201 Wi-Fi Room Thermostat**
- Tuya product ID: `wxmbjwpt8yea7bag`
- Tuya category: `wk`
- Mapping ID: `wxmbjwpt8yea7bag-ef945de926`
- Main platform: `climate`
- Additional entities: holiday temperature and holiday-day controls
- EMOS model: `P56201`
- EAN: `8592920117767`

This mapping is physically verified and preserves product-specific climate
behaviour that cannot be safely inferred from generic Tuya metadata alone.

## Contributing a device mapping

### Recommended: LocalTuya configuration flow

Configure the device correctly in LocalTuya first. Then open the LocalTuya
configuration menu and choose:

`Prepare community contribution`

Select the configured device and let LocalTuya generate the contribution
package from the configuration already working in Home Assistant. Review the
generated JSON before submitting it.

### Alternative: Home Assistant action/service

LocalTuya also provides:

`localtuya.export_device_mapping`

with the configured Tuya device ID as input. The device ID is used only to
locate the configured device and must not be included in the exported mapping.

## Privacy requirements

A contribution must never contain:

- Local Key
- Tuya Device ID
- IP address or hostname
- Cloud Client ID
- Cloud Client Secret
- Tuya User ID
- usernames
- region/account credentials
- user-specific friendly names

If any credential or user-specific identifier is present, do not submit the
file.

## Submitting the mapping

Place the exported JSON in:

`submissions/<mapping-id>.json`

Then open a pull request against this repository. GitHub Actions validates
submissions automatically.

A valid submission remains `experimental` until it is promoted through the
trusted promotion workflow. Promotion to `community` publishes the mapping into
`catalog.json`; a later promotion to `verified` records physical validation.

## Imported device knowledge

Repository tooling may analyze or convert device definitions from compatible
open-source projects. Importing source knowledge does **not** make a mapping
trusted automatically.

Imported mappings must:

1. preserve upstream license attribution
2. record source provenance when available
3. be representable without silently dropping required behaviour
4. enter as `experimental`
5. follow the same review and physical-verification lifecycle as native
   submissions

The Tuya Local import tooling is intentionally fail-closed: unsupported or
ambiguous profiles are skipped rather than partially published.

See `THIRD_PARTY_NOTICES.md` for third-party attribution.

## Mapping requirements

A useful product-specific mapping should contain, when known:

1. Real Tuya product ID(s).
2. Tuya category.
3. Required datapoints that safely fingerprint the device behaviour.
4. Optional datapoints for firmware/product capabilities that may be absent.
5. Entity configuration that can be represented by LocalTuya.
6. Appropriate confidence level.
7. Provenance when derived from third-party open-source device knowledge.

Mappings describe behaviour, not user-specific device identity. Do not invent
missing datapoints or copy a generic test fixture into the catalog as if it were
a real product.

## Remote catalog and bundled snapshot

`catalog.json` is the current remote catalog consumed by LocalTuya.
LocalTuya also ships a bundled snapshot at:

`custom_components/localtuya/builtin_catalog.json`

The bundled snapshot provides a known-good offline fallback when the remote
catalog cannot be downloaded. Verified mappings may therefore also be
synchronized into the LocalTuya repository when preparing a release.

The remote catalog remains independently updateable between compatible
LocalTuya releases.

## Refreshing the catalog in LocalTuya

LocalTuya provides:

`localtuya.refresh_device_catalog`

to request a fresh copy of the remote catalog without reinstalling the
integration.

## Security model

This repository contains data only. Mappings cannot contain Python code,
scripts or executable expressions.

LocalTuya validates catalog structure before accepting it, checks required
DPS against datapoints actually detected from the local device, and ignores
optional capabilities that are not present.

Credential, account and network identity fields are not valid catalog
configuration.

## Catalog format

Current schema version:

`2`

The formal schema is available in:

`schema/catalog.schema.json`
