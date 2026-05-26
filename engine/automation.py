"""
Parameter automation curves for Mantice.

V1/V2: simple start→end ramp with a single curve shape.
V3:    arbitrary breakpoints — multiple (t, value, shape) tuples per parameter.
V3+:   random walk — smooth seeded noise that orbits a center value.

All formats are supported in YAML presets and the JS UI.
Automation is opt-in per parameter — off by default.
"""

from __future__ import annotations
import math
import numpy as np
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


# ── Random Walk Curve ─────────────────────────────────────────────────────────

# Maps the three named speed presets to cycles-per-render
_WALK_SPEED_MAP: dict[str, float] = {
    "slow": 0.25,
    "med":  0.85,
    "fast": 2.5,
}


class RandomWalkCurve:
    """
    A smooth, seeded random walk for a parameter.

    Instead of authored breakpoints, the value orbits a center
    value within ±depth using a sum of incommensurate sinusoids
    (no external dependencies, fully deterministic from seed).

    YAML format:
        {enabled: true, mode: random_walk,
         center: 1200, depth: 800, speed: slow}

    speed choices: slow | med | fast
    """

    SPEEDS = tuple(_WALK_SPEED_MAP.keys())
    _TABLE_SIZE = 1024

    def __init__(
        self,
        center: float,
        depth: float,
        speed: str = "med",
        seed: int = 42,
        enabled: bool = True,
    ) -> None:
        self.center  = float(center)
        self.depth   = float(depth)
        self.speed   = speed if speed in _WALK_SPEED_MAP else "med"
        self.enabled = bool(enabled)
        self._table  = self._generate(seed)

    def _generate(self, seed: int) -> np.ndarray:
        """Precompute smooth noise table in [-1, 1] from seed."""
        rng = np.random.RandomState(int(seed) % (2 ** 32))
        N = self._TABLE_SIZE
        t = np.linspace(0.0, 1.0, N)
        cycles = _WALK_SPEED_MAP[self.speed]
        signal = np.zeros(N, dtype=np.float64)
        for k in range(6):
            freq  = cycles * (k + 1) * rng.uniform(0.75, 1.25)
            phase = rng.uniform(0.0, 2.0 * math.pi)
            amp   = 1.0 / (k + 1)
            signal += amp * np.sin(2.0 * math.pi * freq * t + phase)
        peak = np.abs(signal).max()
        if peak > 0.0:
            signal /= peak
        return signal.astype(np.float32)

    def value_at(self, t_norm: float) -> float:
        """Return interpolated value at normalised time t_norm ∈ [0, 1]."""
        if not self.enabled:
            return self.center
        t = max(0.0, min(1.0, float(t_norm)))
        idx = t * (self._TABLE_SIZE - 1)
        i0  = int(idx)
        i1  = min(i0 + 1, self._TABLE_SIZE - 1)
        frac = idx - i0
        raw = float(self._table[i0]) * (1.0 - frac) + float(self._table[i1]) * frac
        return self.center + self.depth * raw

    @classmethod
    def from_dict(cls, d: dict[str, Any], seed: int = 42) -> "RandomWalkCurve":
        return cls(
            center  = float(d.get("center", 0.0)),
            depth   = float(d.get("depth", 0.0)),
            speed   = str(d.get("speed", "med")),
            seed    = seed,
            enabled = bool(d.get("enabled", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode":    "random_walk",
            "enabled": self.enabled,
            "center":  self.center,
            "depth":   self.depth,
            "speed":   self.speed,
        }

    def __repr__(self) -> str:
        return (
            f"RandomWalkCurve(center={self.center}, depth={self.depth}, "
            f"speed={self.speed!r}, enabled={self.enabled})"
        )


def _curve_from_dict(d: dict[str, Any], seed: int = 42) -> "AutomationCurve | RandomWalkCurve":
    """Factory: returns the correct curve type based on the 'mode' field."""
    if d.get("mode") == "random_walk":
        return RandomWalkCurve.from_dict(d, seed=seed)
    return AutomationCurve.from_dict(d)




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
    "saturation":        (0.0,   1.0),
}


def _clamp_curve(curve: "AutomationCurve | RandomWalkCurve", lo: float, hi: float) -> "AutomationCurve | RandomWalkCurve":
    """Clamp values to [lo, hi]. For breakpoint curves, clamps each node value.
    For random walk curves, clamps center and ensures depth doesn't exceed range."""
    if isinstance(curve, RandomWalkCurve):
        curve.center = max(lo, min(hi, curve.center))
        max_depth = (hi - lo) / 2.0
        curve.depth = min(curve.depth, max_depth)
        return curve
    # AutomationCurve
    curve.breakpoints = [
        (t, max(lo, min(hi, v)), s) for t, v, s in curve.breakpoints
    ]
    return curve


def parse_layer_automation(layer_cfg: dict, seed: int = 42) -> dict:
    """Extract automation curves from a layer config dict."""
    result = {}
    auto_block = layer_cfg.get("automation") or {}
    for key in LAYER_AUTO_PARAMS:
        if key in auto_block and isinstance(auto_block[key], dict):
            curve = _curve_from_dict(auto_block[key], seed=seed)
            if curve.enabled:
                lo, hi = LAYER_AUTO_PARAMS[key]
                result[key] = _clamp_curve(curve, lo, hi)
    return result


def parse_global_automation(preset: dict, seed: int = 42) -> dict:
    """Extract global automation curves from a preset dict."""
    result = {}
    auto_block = preset.get("automation") or {}
    for key in GLOBAL_AUTO_PARAMS:
        if key in auto_block and isinstance(auto_block[key], dict):
            curve = _curve_from_dict(auto_block[key], seed=seed)
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
    {
        "name": "wander",
        "desc": "All key params drift on slow random walks — ideal for long, unattended renders",
        "global": {
            "reverb_mix":       {"enabled": True, "mode": "random_walk", "center": 0.45, "depth": 0.25, "speed": "slow"},
            "binaural_beat_hz": {"enabled": True, "mode": "random_walk", "center": 6.0,  "depth": 4.0,  "speed": "slow"},
        },
        "layer": {
            "filter_cutoff": {"enabled": True, "mode": "random_walk", "center": 2000, "depth": 1500, "speed": "med"},
            "fm_index":      {"enabled": True, "mode": "random_walk", "center": 0.8,  "depth": 0.6,  "speed": "slow"},
        },
    },
    {
        "name": "trance",
        "desc": "Binaural wanders theta/delta while reverb breathes — deep entrainment focus",
        "global": {
            "binaural_beat_hz":  {"enabled": True, "mode": "random_walk", "center": 5.0,  "depth": 4.5,  "speed": "slow"},
            "reverb_decay_trim": {"enabled": True, "mode": "random_walk", "center": 0.7,  "depth": 0.25, "speed": "slow"},
            "reverb_mix":        {"enabled": True, "mode": "random_walk", "center": 0.65, "depth": 0.2,  "speed": "slow"},
        },
        "layer": {},
    },
    {
        "name": "shimmer",
        "desc": "Shimmer, air and reverb drift slowly — top-end sparkle never settles",
        "global": {
            "shimmer_wet":   {"enabled": True, "mode": "random_walk", "center": 0.4,  "depth": 0.3,  "speed": "med"},
            "reverb_mix":    {"enabled": True, "mode": "random_walk", "center": 0.5,  "depth": 0.2,  "speed": "slow"},
            "master_air_db": {"enabled": True, "mode": "random_walk", "center": 1.5,  "depth": 3.0,  "speed": "slow"},
        },
        "layer": {},
    },
]
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

