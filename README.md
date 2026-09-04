# LocalTuya Device Catalog

Community-maintained device mapping catalog for the
[LocalTuya fork](https://github.com/MattiaFontana997/localtuya).

The catalog preserves product-specific Tuya mappings that have been observed
and reviewed on real devices, without requiring a new LocalTuya release for
every newly supported product.

## What belongs in the catalog

The catalog is intentionally product-specific.

A catalog entry must use a real Tuya product ID and should only be added when
there is useful device-specific knowledge that the generic LocalTuya mapper
cannot safely infer by itself.

Generic Tuya switches, lights, covers, fans, thermostats, sensors, numbers and
selects should remain handled by LocalTuya's built-in metadata mapper whenever
possible.

See
[`docs/known-device-coverage.md`](docs/known-device-coverage.md)
for the current product-specific inventory and generic LocalTuya coverage.

## How LocalTuya uses the catalog

LocalTuya first builds entities from its built-in generic mapper.

Product-specific catalog mappings can then complete or refine that result when
the device matches the mapping requirements.

A mapping is checked against:

- Tuya product ID
- Tuya category, when available
- datapoints actually detected from the device over the LAN

LocalTuya can use:

- the current remote `catalog.json`
- a persistent local cache
- a bundled `builtin_catalog.json` snapshot as an offline fallback

A remote mapping is never trusted only because its product ID matches.
Required datapoints must also be present on the actual local device.

## Confidence levels

Catalog entries use one of three confidence levels:

- `experimental` — newly submitted mapping awaiting trusted promotion
- `community` — reviewed mapping accepted into the published catalog
- `verified` — community mapping additionally verified on real hardware

The repository enforces the promotion order:

`experimental` → `community` → `verified`

An experimental submission cannot be promoted directly to `verified`.

Promotion to `community` moves the accepted mapping from `submissions/` into
the published `catalog.json`.

Promotion to `verified` is allowed only after the mapping is already
`community` and requires an explicit physical verification note.

Do not mark a mapping as `verified` only because its JSON validates or its
metadata looks correct. The entity behaviour must have been tested on the
physical device.

## Current real product mappings

The published catalog currently contains physically tested product-specific
knowledge for real Tuya hardware.

### LSC Smart Connect RGB+CCT smart light (Action)

- Brand: **LSC Smart Connect**
- Retailer: **Action**
- Tuya product ID: `r7sn2fda7l5hwzvx`
- Tuya category: `dj`
- Mapping ID: `r7sn2fda7l5hwzvx-0cc115f608`
- Platform: `light`
- Protocol physically tested: **Tuya 3.5**
- Required DPS:
  - DP 20 — power
  - DP 21 — work/color mode
  - DP 22 — brightness
  - DP 23 — color temperature
  - DP 24 — RGB/HSV color

Power, brightness, color temperature, color and spontaneous device/Tuya app
state updates back to Home Assistant have been tested on real hardware.

The exact Action retail article number is not recorded; matching is performed
using the Tuya product ID and detected LAN datapoints rather than the retail
SKU.

### EMOS GoSmart P56201 Wi-Fi Room Thermostat

- Brand: **EMOS**
- Product: **GoSmart P56201 Wi-Fi Room Thermostat**
- Tuya product ID: `wxmbjwpt8yea7bag`
- Tuya category: `wk`
- Mapping ID: `wxmbjwpt8yea7bag-ef945de926`
- Main platform: `climate`
- Additional entities: holiday temperature and holiday-day controls
- Retail reference: Amazon ASIN `B0BS3TL7DC`
- EMOS model: `P56201`
- EAN: `8592920117767`

This mapping is physically verified and preserves product-specific climate
behaviour that cannot be safely inferred from generic Tuya metadata alone.

## Contributing a device mapping

### Recommended: LocalTuya configuration flow

Configure the device correctly in LocalTuya first.

Then open the LocalTuya configuration menu and choose:

`Prepare community contribution`

Select the configured device and let LocalTuya generate the contribution
package from the configuration that is already working in Home Assistant.

Review the generated JSON before submitting it.

### Alternative: Home Assistant action/service

LocalTuya also provides:

`localtuya.export_device_mapping`

with the configured Tuya device ID as input.

The device ID is used only to locate the configured device and must not be
included in the exported mapping.

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

Then open a pull request against this repository.

GitHub Actions validates submissions automatically.

A valid submission remains `experimental` until it is promoted through the
trusted promotion workflow.

Promotion to `community` publishes the mapping into `catalog.json`.
A later promotion to `verified` records that the mapping has also been
physically validated on real hardware.

## Mapping requirements

A useful product-specific mapping should contain, when known:

1. Real Tuya product ID.
2. Tuya category.
3. Datapoints actually observed on the device.
4. Entity configuration that has been tested.
5. Appropriate confidence level.

Mappings should describe behaviour, not user-specific device identity.

Do not invent missing datapoints or copy a generic test fixture into the
catalog as if it were a real product.

## Remote catalog and bundled snapshot

`catalog.json` is the current remote catalog consumed by LocalTuya.

LocalTuya also ships a bundled snapshot:

`custom_components/localtuya/builtin_catalog.json`

The bundled snapshot provides a known-good offline fallback when the remote
catalog cannot be downloaded.

Verified mappings may therefore also be synchronized into the LocalTuya
repository when preparing a release.

The remote catalog remains independently updateable between LocalTuya releases.

## Refreshing the catalog in LocalTuya

LocalTuya provides:

`localtuya.refresh_device_catalog`

to request a fresh copy of the remote catalog without reinstalling the
integration.

## Security model

This repository contains data only.

Mappings cannot contain Python code, scripts or executable expressions.

LocalTuya validates catalog structure before accepting it and checks required
datapoints against the datapoints actually detected from the local device.

Credential, account and network identity fields are not valid catalog
configuration.

## Catalog format

Current schema version:

`1`

The formal schema is available in:

`schema/catalog.schema.json`
