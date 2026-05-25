"""
Parameter automation curves for Mantice.

V1/V2: simple start→end ramp with a single curve shape.
V3:    arbitrary breakpoints — multiple (t, value, shape) tuples per parameter.

Both formats are supported in YAML presets and the JS UI.
Automation is opt-in per parameter — off by default.
"""

from __future__ import annotations
import math
from typing import Any


def _apply_shape(t: float, shape: str) -> float:
    """Map normalised time t ∈ [0,1] through a curve shape."""
    if shape == "scurve":
        return t * t * (3.0 - 2.0 * t)          # Hermite smooth-step
    elif shape == "exp":
        k = 4.0                                   # exponential ease-in
        if t == 0.0:
            return 0.0
        return (math.exp(k * t) - 1.0) / (math.exp(k) - 1.0)
    else:                                         # linear (default)
        return t


class AutomationCurve:
    """
    A time-varying parameter defined by a sorted list of breakpoints.

    Each breakpoint: (t_norm, value, shape)
      t_norm — position in [0, 1] across the full render duration
      value  — parameter value at this breakpoint
      shape  — interpolation shape used for the segment FROM the previous
               breakpoint TO this one (ignored on the first breakpoint)

    Accepted shapes: "linear", "scurve", "exp"

    YAML formats accepted by from_dict():

      V1/V2 (two-point ramp — backward-compatible):
        {enabled: true, start: 200, end: 4000, shape: exp}

      V3 (arbitrary breakpoints):
        {enabled: true, breakpoints:
          [{t: 0.0, value: 200},
           {t: 0.5, value: 4000, shape: exp},
           {t: 1.0, value: 800,  shape: scurve}]}
    """

    SHAPES = ("linear", "scurve", "exp")

    def __init__(
        self,
        breakpoints: list[tuple[float, float, str]],
        enabled: bool = True,
    ) -> None:
        # Normalise and sort; default shape = "linear"
        self.breakpoints: list[tuple[float, float, str]] = sorted(
            (
                (
                    max(0.0, min(1.0, float(t))),
                    float(v),
                    (s if s in self.SHAPES else "linear"),
                )
                for t, v, s in breakpoints
            ),
            key=lambda x: x[0],
        )
        self.enabled = bool(enabled)

    # ── Value evaluation ──────────────────────────────────────────────────────

    def value_at(self, t_norm: float) -> float:
        """Return interpolated value at normalised time t_norm ∈ [0, 1]."""
        pts = self.breakpoints
        if not pts:
            return 0.0
        if not self.enabled:
            return pts[0][1]

        t = max(0.0, min(1.0, float(t_norm)))

        # Clamp to first/last breakpoint
        if t <= pts[0][0]:
            return pts[0][1]
        if t >= pts[-1][0]:
            return pts[-1][1]

        # Find the enclosing segment and interpolate
        for i in range(len(pts) - 1):
            t0, v0, _     = pts[i]
            t1, v1, shape = pts[i + 1]
            if t0 <= t <= t1:
                span = t1 - t0
                if span == 0.0:
                    return v1
                local_t = (t - t0) / span
                return v0 + (v1 - v0) * _apply_shape(local_t, shape)

        return pts[-1][1]

    # ── Serialisation ─────────────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AutomationCurve":
        """
        Accept both V1/V2 {start, end, shape} and V3 {breakpoints: [...]} formats.
        V1/V2 is silently promoted to a two-breakpoint V3 curve.
        """
        enabled = bool(d.get("enabled", True))

        if "breakpoints" in d:
            # V3 format
            bps: list[tuple[float, float, str]] = []
            for bp in d["breakpoints"]:
                t = float(bp.get("t", 0.0))
                v = float(bp.get("value", 0.0))
                s = str(bp.get("shape", "linear"))
                bps.append((t, v, s))
        else:
            # V1/V2 format — promote to two breakpoints
            start = float(d.get("start", 0.0))
            end   = float(d.get("end",   0.0))
            shape = str(d.get("shape", "linear"))
            bps = [(0.0, start, "linear"), (1.0, end, shape)]

        return cls(bps, enabled=enabled)

    def to_dict(self) -> dict[str, Any]:
        """Always serialise as V3 breakpoint format."""
        return {
            "enabled": self.enabled,
            "breakpoints": [
                {"t": t, "value": v, "shape": s}
                for t, v, s in self.breakpoints
            ],
        }

    def __repr__(self) -> str:
        return (
            f"AutomationCurve(breakpoints={self.breakpoints!r}, "
            f"enabled={self.enabled})"
        )


# ── Per-preset automation structure ──────────────────────────────────────────

# Automatable per-layer parameters with (min, max) clamp ranges
LAYER_AUTO_PARAMS: dict[str, tuple[float, float]] = {
    "filter_cutoff":    (20.0,   20000.0),
    "fm_index":         (0.0,    5.0),
    "distortion_drive": (0.0,    5.0),
    "volume_db":        (-60.0,  6.0),
    "width":            (0.0,    2.0),
    "chorus_rate":      (0.01,   5.0),
    "lfo_rate":         (0.01,   5.0),
    "detune_cents":     (0.0,    50.0),
    "granular_position":(0.0,    1.0),
}

# Automatable global parameters with (min, max) clamp ranges
GLOBAL_AUTO_PARAMS: dict[str, tuple[float, float]] = {
    "reverb_mix":        (0.0,   1.0),
    "reverb_decay_trim": (0.0,   1.0),
    "shimmer_wet":       (0.0,   1.0),
    "binaural_beat_hz":  (0.5,   40.0),
    "master_air_db":     (-12.0, 12.0),
    "master_output_db":  (-12.0, 6.0),
}


def _clamp_curve(curve: AutomationCurve, lo: float, hi: float) -> AutomationCurve:
    """Clamp all breakpoint values to [lo, hi] in-place and return the curve."""
    curve.breakpoints = [
        (t, max(lo, min(hi, v)), s) for t, v, s in curve.breakpoints
    ]
    return curve


def parse_layer_automation(layer_cfg: dict) -> dict[str, AutomationCurve]:
    """Extract automation curves from a layer config dict."""
    result: dict[str, AutomationCurve] = {}
    auto_block = layer_cfg.get("automation") or {}
    for key in LAYER_AUTO_PARAMS:
        if key in auto_block and isinstance(auto_block[key], dict):
            curve = AutomationCurve.from_dict(auto_block[key])
            if curve.enabled:
                lo, hi = LAYER_AUTO_PARAMS[key]
                result[key] = _clamp_curve(curve, lo, hi)
    return result


def parse_global_automation(preset: dict) -> dict[str, AutomationCurve]:
    """Extract global automation curves from a preset dict."""
    result: dict[str, AutomationCurve] = {}
    auto_block = preset.get("automation") or {}
    for key in GLOBAL_AUTO_PARAMS:
        if key in auto_block and isinstance(auto_block[key], dict):
            curve = AutomationCurve.from_dict(auto_block[key])
            if curve.enabled:
                lo, hi = GLOBAL_AUTO_PARAMS[key]
                result[key] = _clamp_curve(curve, lo, hi)
    return result


# ── Global automation templates ───────────────────────────────────────────────

# Each template is a dict with:
#   "name"   — display name (lowercase slug used as CLI arg)
#   "desc"   — one-line description
#   "global" — dict of global param → breakpoint list
#   "layer"  — dict of layer param  → breakpoint list (applied to ALL enabled layers)
#
# Breakpoint format: {"t": float, "value": float, "shape": "linear"|"exp"|"scurve"}

AUTO_TEMPLATES: list[dict] = [
    {
        "name": "journey",
        "desc": "Fade in · filter opens · reverb builds · binaural drifts alpha→delta",
        "global": {
            "master_output_db": {"enabled": True, "breakpoints": [
                {"t": 0.0, "value": -20, "shape": "linear"},
                {"t": 0.2, "value": 0,   "shape": "exp"},
            ]},
            "reverb_mix": {"enabled": True, "breakpoints": [
                {"t": 0.0, "value": 0.1,  "shape": "linear"},
                {"t": 1.0, "value": 0.75, "shape": "scurve"},
            ]},
            "binaural_beat_hz": {"enabled": True, "breakpoints": [
                {"t": 0.0, "value": 10.0, "shape": "linear"},
                {"t": 1.0, "value": 2.5,  "shape": "exp"},
            ]},
        },
        "layer": {
            "filter_cutoff": {"enabled": True, "breakpoints": [
                {"t": 0.0, "value": 300,  "shape": "linear"},
                {"t": 1.0, "value": 5000, "shape": "exp"},
            ]},
        },
    },
    {
        "name": "arc",
        "desc": "Output builds to peak then fades · reverb follows the arc",
        "global": {
            "master_output_db": {"enabled": True, "breakpoints": [
                {"t": 0.0, "value": -12, "shape": "linear"},
                {"t": 0.5, "value": 0,   "shape": "scurve"},
                {"t": 1.0, "value": -12, "shape": "scurve"},
            ]},
            "reverb_mix": {"enabled": True, "breakpoints": [
                {"t": 0.0, "value": 0.1, "shape": "linear"},
                {"t": 0.5, "value": 0.7, "shape": "scurve"},
                {"t": 1.0, "value": 0.2, "shape": "scurve"},
            ]},
        },
        "layer": {},
    },
    {
        "name": "breathe",
        "desc": "Slow filter arc · volume gently pulses once",
        "global": {
            "master_output_db": {"enabled": True, "breakpoints": [
                {"t": 0.00, "value": -4, "shape": "linear"},
                {"t": 0.45, "value": 0,  "shape": "scurve"},
                {"t": 1.00, "value": -6, "shape": "scurve"},
            ]},
        },
        "layer": {
            "filter_cutoff": {"enabled": True, "breakpoints": [
                {"t": 0.0, "value": 500,  "shape": "linear"},
                {"t": 0.5, "value": 4000, "shape": "scurve"},
                {"t": 1.0, "value": 400,  "shape": "scurve"},
            ]},
        },
    },
    {
        "name": "meditate",
        "desc": "Binaural drifts alpha → delta · reverb deepens slowly",
        "global": {
            "binaural_beat_hz": {"enabled": True, "breakpoints": [
                {"t": 0.0, "value": 10.0, "shape": "linear"},
                {"t": 1.0, "value": 1.5,  "shape": "exp"},
            ]},
            "reverb_mix": {"enabled": True, "breakpoints": [
                {"t": 0.0, "value": 0.2,  "shape": "linear"},
                {"t": 1.0, "value": 0.85, "shape": "scurve"},
            ]},
            "reverb_decay_trim": {"enabled": True, "breakpoints": [
                {"t": 0.0, "value": 0.3, "shape": "linear"},
                {"t": 1.0, "value": 1.0, "shape": "scurve"},
            ]},
        },
        "layer": {},
    },
    {
        "name": "sunrise",
        "desc": "Very slow fade in · shimmer emerges in the last third",
        "global": {
            "master_output_db": {"enabled": True, "breakpoints": [
                {"t": 0.0, "value": -30, "shape": "linear"},
                {"t": 0.6, "value": 0,   "shape": "exp"},
            ]},
            "shimmer_wet": {"enabled": True, "breakpoints": [
                {"t": 0.65, "value": 0,    "shape": "linear"},
                {"t": 1.0,  "value": 0.45, "shape": "scurve"},
            ]},
            "master_air_db": {"enabled": True, "breakpoints": [
                {"t": 0.0, "value": -3, "shape": "linear"},
                {"t": 0.8, "value": 3,  "shape": "scurve"},
            ]},
        },
        "layer": {},
    },
]

# Quick lookup by name
_TEMPLATE_BY_NAME: dict[str, dict] = {t["name"]: t for t in AUTO_TEMPLATES}
TEMPLATE_NAMES: list[str] = [t["name"] for t in AUTO_TEMPLATES]


def apply_auto_template(preset: dict, template_name: str) -> None:
    """
    Merge an automation template into a preset dict (in-place).
    Only sets a parameter if it is not already enabled in the preset,
    so explicitly-authored automation is never overwritten.

    Args:
        preset:        The loaded preset dict (modified in-place).
        template_name: One of the names in TEMPLATE_NAMES (case-insensitive).

    Raises:
        ValueError: if template_name is not recognised.
    """
    key = template_name.lower()
    if key not in _TEMPLATE_BY_NAME:
        raise ValueError(
            f"Unknown automation template '{template_name}'. "
            f"Available: {', '.join(TEMPLATE_NAMES)}"
        )
    tpl = _TEMPLATE_BY_NAME[key]

    # -- global automation block ------------------------------------------
    preset.setdefault("automation", {})
    for param, curve in tpl["global"].items():
        existing = preset["automation"].get(param)
        if isinstance(existing, dict) and existing.get("enabled"):
            continue  # don't overwrite an already-enabled curve
        preset["automation"][param] = curve

    # -- layer automation (applied to every enabled layer) ----------------
    if tpl["layer"]:
        for layer in preset.get("layers", []):
            if not layer.get("enabled", True):
                continue
            layer.setdefault("automation", {})
            for param, curve in tpl["layer"].items():
                existing = layer["automation"].get(param)
                if isinstance(existing, dict) and existing.get("enabled"):
                    continue
                layer["automation"][param] = curve


def strip_automation(preset: dict) -> None:
    """Remove all automation blocks from a preset dict (in-place)."""
    preset.pop("automation", None)
    for layer in preset.get("layers", []):
        layer.pop("automation", None)

