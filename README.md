# LocalTuya Device Catalog

Community-maintained device mapping catalog for the
[LocalTuya fork](https://github.com/MattiaFontana997/localtuya).

The catalog lets LocalTuya learn verified product-specific mappings
without requiring a new LocalTuya release for every supported device.

## How it works

LocalTuya downloads `catalog.json` and validates a mapping against:

- Tuya product ID
- Tuya category, when available
- datapoints actually detected over LAN

The built-in LocalTuya mapper always has priority.

Remote mappings may extend existing mappings, but must not remove or
replace behaviour already detected by the built-in mapper.

The catalog intentionally does **not** duplicate every generic device family
that LocalTuya already understands. Product-specific catalog entries require a
real Tuya product ID; generic switches, lights, covers, fans, thermostats,
sensors and other metadata-driven entities remain handled by the built-in
mapper.

See [`docs/known-device-coverage.md`](docs/known-device-coverage.md) for the
current inventory of product-specific mappings and generic coverage already
known by the project.

## Confidence levels

- `experimental` — submitted but not sufficiently confirmed
- `verified` — manually verified on real hardware
- `community` — confirmed by multiple independent users/devices

LocalTuya may show experimental mappings for review.

Verified/community mappings can be treated with higher confidence.

## Contributing a device mapping

LocalTuya can generate a sanitized mapping using:

`localtuya.export_device_mapping`

The exported mapping must not contain:

- Local Key
- Tuya Device ID
- IP address
- Cloud Client ID
- Cloud Client Secret
- Tuya User ID
- usernames
- region/account credentials
- user-specific friendly names

Place the exported JSON in:

`submissions/<mapping-id>.json`

and open a pull request.

Every submission is automatically validated by GitHub Actions.

## Security

This repository contains data only.

Mappings cannot contain Python code, scripts or executable expressions.

LocalTuya independently checks the required datapoints against the
datapoints actually detected from the local Tuya device before applying
a catalog mapping.

## Catalog format

Current schema version:

`1`

The formal schema is available in:

`schema/catalog.schema.json`
