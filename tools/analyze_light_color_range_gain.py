"""Measure Tuya Local import coverage with independent HSV value ranges.

This is a temporary analysis wrapper around the conservative importer. It uses
exactly the runtime capability added to LocalTuya: when the standard HSV value
range differs from the white brightness range, emit dedicated catalog config
keys instead of rejecting the profile.
"""

from __future__ import annotations

from typing import Any

import import_tuya_local as importer


_original_configure_light_scale = importer._configure_light_scale


def _configure_light_scale(
    config: dict[str, Any],
    *,
    minimum: int,
    maximum: int,
    reason: str,
    require_lower: bool,
) -> None:
    if reason != "light_rgbhsv":
        _original_configure_light_scale(
            config,
            minimum=minimum,
            maximum=maximum,
            reason=reason,
            require_lower=require_lower,
        )
        return

    existing_lower = config.get("brightness_lower")
    existing_upper = config.get("brightness_upper")

    # If no white/CCT scale established a shared range yet, keep using the
    # legacy brightness keys. No new runtime config is needed in that case.
    if existing_lower is None and existing_upper is None:
        config["brightness_lower"] = minimum
        config["brightness_upper"] = maximum
        return

    if existing_lower == minimum and existing_upper == maximum:
        return

    # LocalTuya runtime now supports an independent raw V range for the
    # standard 12-character Tuya HSV payload.
    config["color_brightness_lower"] = minimum
    config["color_brightness_upper"] = maximum


importer._configure_light_scale = _configure_light_scale


if __name__ == "__main__":
    raise SystemExit(importer.main())
