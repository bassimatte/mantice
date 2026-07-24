"""Pure discovery metadata derived from UI-normalized preset parameters."""

from __future__ import annotations

from typing import Any


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result


def summarize_preset(params: dict) -> dict:
    """Build compact, gallery-safe metadata without rendering audio."""
    if not isinstance(params, dict):
        return {}

    layers = [
        layer for layer in (params.get("layers") or [])
        if isinstance(layer, dict)
    ]
    roots: list[float] = []
    synth_types: list[str] = []
    widths: list[float] = []
    moving = False
    fingerprint = []

    for index, layer in enumerate(layers):
        root = _number(layer.get("root", layer.get("base_freq")))
        if root is not None and root > 0:
            roots.append(root)
        else:
            root = None

        synth_type = str(layer.get("type") or "fm").lower()
        if synth_type not in synth_types:
            synth_types.append(synth_type)

        width = _number(layer.get("width", 1), 1.0) or 1.0
        widths.append(width)
        motion = layer.get("spatial_motion") or {}
        trajectory = str(
            motion.get("trajectory_x", layer.get("trajectory_x", "none"))
            or "none"
        ).lower()
        moving = moving or trajectory not in ("none", "static", "off")
        volume_db = _number(layer.get("volume_db", 0), 0.0) or 0.0
        motion_speed = _number(
            motion.get("speed", layer.get("speed", 0)),
            0.0,
        ) or 0.0
        fingerprint.append({
            "index": index,
            "name": str(layer.get("name") or f"Layer {index + 1}"),
            "root": round(root, 2) if root is not None else None,
            "volume_db": round(volume_db, 2),
            "width": round(width, 2),
            "type": synth_type,
            "trajectory": trajectory,
            "motion_speed": round(motion_speed, 4),
        })

    traits = list(synth_types)
    lowest_hz = min(roots) if roots else None
    if lowest_hz is not None and lowest_hz < 80:
        traits.append("sub-heavy")
    if len(layers) >= 4:
        traits.append("dense")
    if widths and sum(widths) / len(widths) > 1.15:
        traits.append("wide")
    if moving:
        traits.append("motion")

    reverb = params.get("reverb") or {}
    reverb_mix = _number(reverb.get("mix", reverb.get("wet", 0)), 0.0) or 0.0
    if reverb.get("enabled") and reverb_mix >= 0.3:
        traits.append("deep space")
    shimmer = params.get("shimmer") or {}
    shimmer_wet = _number(shimmer.get("wet", 0), 0.0) or 0.0
    if shimmer_wet >= 0.08:
        traits.append("shimmer")
    binaural = params.get("binaural") or {}
    if binaural.get("enabled"):
        traits.append("binaural")
    tuning = (
        params.get("tuning_system_ji")
        if params.get("tuning_mode") == "ji"
        else params.get("tuning_system")
    )
    if params.get("tuning_mode") == "ji":
        traits.append("just intonation")

    return {
        "layer_count": len(layers),
        "lowest_hz": round(lowest_hz, 1) if lowest_hz is not None else None,
        "synth_types": synth_types,
        "traits": list(dict.fromkeys(traits))[:6],
        "duration": params.get("duration"),
        "tuning": tuning or "12-TET",
        "complexity": len(layers) + len(traits),
        "fingerprint": fingerprint,
        "reverb_mix": round(reverb_mix, 3),
        "shimmer_wet": round(shimmer_wet, 3),
    }
