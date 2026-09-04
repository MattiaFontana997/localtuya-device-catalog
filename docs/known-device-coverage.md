# Known device coverage

This document separates **product-specific catalog mappings** from the
**generic device families already understood by LocalTuya**.

The distinction is intentional: `catalog.json` is product-specific. Its schema
requires a real Tuya `product_id`, category information, and datapoints that
must actually be present on the device. Generic Tuya patterns must not be
invented as fake catalog products.

## Product-specific catalog mappings

### Verified

#### LSC Smart Connect RGB+CCT smart light (Action)

- Mapping ID: `r7sn2fda7l5hwzvx-0cc115f608`
- Brand: LSC Smart Connect
- Retailer: Action
- Product ID: `r7sn2fda7l5hwzvx`
- Category: `dj`
- Platform: light
- Protocol physically tested: Tuya 3.5
- Required DPS:
  - `20` — power
  - `21` — work/color mode
  - `22` — brightness
  - `23` — color temperature
  - `24` — RGB/HSV color
- Physically validated for power, brightness, color temperature, color and
  spontaneous device/Tuya app updates back to Home Assistant.
- The exact Action retail SKU is not recorded; the catalog identifies the
  product through its Tuya product ID and LAN DPS fingerprint.

#### EMOS GoSmart P56201 Wi-Fi Room Thermostat

- Mapping ID: `wxmbjwpt8yea7bag-ef945de926`
- Brand: EMOS
- Commercial model: GoSmart P56201 Wi-Fi Room Thermostat
- Product ID: `wxmbjwpt8yea7bag`
- Category: `wk`
- Amazon ASIN: `B0BS3TL7DC`
- EAN: `8592920117767`
- Platforms: climate plus number entities for product-specific holiday
  temperature/day controls
- Physically verified on the real thermostat.

## Generic LocalTuya coverage

The LocalTuya generic mapper can already configure the following device
families from Tuya Cloud/TinyTuya metadata. These normally **do not need a
catalog entry** unless a concrete product has undocumented DPS, non-standard
semantics, or other behavior that the generic mapper cannot safely infer.

### Lights

High-confidence light detection uses writable Boolean `switch_led` or
`switch_led_1`. It can also consume, when metadata is compatible:

- `bright_value_v2` / `bright_value`
- `temp_value_v2` / `temp_value`
- `work_mode`
- string/raw `colour_data` / `color_data`
- string/raw `colour_data_v2` / `color_data_v2`

The v2 color datapoints are mapped only when Tuya metadata reports a compatible
string/raw representation. Structured JSON variants are deliberately not
treated as LocalTuya encoded color strings.

### Thermostats

Category `wk` is generically recognized when the canonical thermostat metadata
is present:

- `switch`
- `temp_set`
- `temp_current`

Temperature scale, range, unit, and supported step are taken from metadata.
`mode` is used as a preset only when its options are exactly `auto`, `manual`,
and `holiday`.

Generic mapping deliberately does **not** infer undocumented HVAC mode DPS.
Those are exactly the kind of product-specific differences that belong in this
catalog.

### Covers / curtains

Categories:

- `cl`
- `clkg`

Recognized control codes are `control` and `control_2` when the enum includes
`open`, `stop`, and `close`. Position support is enabled when compatible 0..100
`percent_control*` and readable `percent_state*` metadata are available.

### Fans and ceiling fan/light units

Categories:

- `fs`
- `fsd`

The generic mapper supports the category-appropriate `switch` / `fan_switch`,
integer or enum fan speed, one oscillation DP (horizontal preferred, then
vertical), and `fan_direction` when `forward` / `reverse` are available.

An `fsd` unit can expose the fan and a separate light when standard light DPS
are also present.

### Generic switches

Writable Boolean datapoints whose code is `switch` or starts with `switch_`
are mapped at high confidence, except codes reserved for specialized entities
such as light power and fan oscillation.

### Binary sensors

Read-only Boolean metadata is recognized for these semantic groups:

- Door/opening: `doorcontact_state`, `door_contact`, `contact_state`
- Motion/occupancy: `pir`, `pir_state`, `motion`, `motion_state`, `presence`,
  `presence_state`, `occupancy`
- Moisture: `water_sensor_state`, `water_leak`
- Smoke: `smoke_sensor_state`, `smoke_alarm`
- Gas: `gas_sensor_state`, `gas_alarm`
- Tamper: `tamper`, `tamper_alarm`
- Low battery: `battery_low`, `low_battery`

Writable Boolean controls are intentionally not converted into binary sensors.

### Measurement sensors

High-confidence measurement sensors are recognized for:

- Voltage: `cur_voltage`, `voltage`
- Current: `cur_current`, `current`
- Power: `cur_power`, `power`
- Temperature: `temp_current`

Units and decimal scaling are taken from Tuya metadata when available.

### Numbers

Any otherwise-unconsumed writable numeric DP can be proposed as a
medium-confidence number when valid `min`, `max`, `step`, and `scale` metadata
exist.

### Selects

Any otherwise-unconsumed writable enum with at least two valid options can be
proposed as a medium-confidence select.

### Vacuums

The LocalTuya integration supports the vacuum platform, but the current generic
mapper does not create vacuum candidates automatically. A real vacuum mapping
can therefore be a useful catalog contribution when its product ID and DPS are
known.

## Known regression fixtures that are not catalog products

The test suite contains representative metadata for a CCT light, a standard
curtain, a standard fan, and an `fsd` ceiling fan/light. Those fixtures prove
generic mapping behavior, but they do not contain trustworthy real Tuya product
IDs. They must therefore **not** be copied into `catalog.json` as
product-specific mappings.

## When to add a catalog entry

Add a product-specific mapping only when all of the following are known:

1. The real Tuya product ID.
2. The category, when available.
3. DPS actually observed on the local device.
4. At least one entity/configuration detail that is useful for that product.

Use `experimental` for a real product mapping that still needs confirmation,
`verified` after physical verification, and `community` according to the
project's promotion policy.

The catalog should stay small when generic mapping is sufficient. Its purpose
is to preserve product-specific knowledge, not duplicate the generic mapper.
