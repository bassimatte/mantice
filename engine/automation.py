"""
Parameter automation curves for Mantice.

Supports linear, S-curve, and exponential interpolation across render duration.
Automation is opt-in per parameter — off by default.
"""

from __future__ import annotations
import math
from typing import Any


class AutomationCurve:
    """
    A time-varying parameter value: interpolates start→end over [0, 1] normalised time.

    Shapes:
      linear    — constant rate of change
      scurve    — smooth sigmoid (slow start, fast middle, slow end)
      exp       — exponential ease-in (slow start, accelerates toward end)
    """

    SHAPES = ("linear", "scurve", "exp")

    def __init__(
        self,
        start: float,
        end: float,
        shape: str = "linear",
        enabled: bool = True,
    ) -> None:
        self.start = float(start)
        self.end = float(end)
        self.shape = shape if shape in self.SHAPES else "linear"
        self.enabled = bool(enabled)

    # ── Value evaluation ──────────────────────────────────────────────────────

    def value_at(self, t_norm: float) -> float:
        """Return interpolated value at normalised time t_norm ∈ [0, 1]."""
        if not self.enabled:
            return self.start
        t = max(0.0, min(1.0, float(t_norm)))
        t_shaped = self._shape(t)
        return self.start + (self.end - self.start) * t_shaped

    def _shape(self, t: float) -> float:
        if self.shape == "scurve":
            # Smooth sigmoid: 3t² − 2t³  (Hermite interpolation)
            return t * t * (3.0 - 2.0 * t)
        elif self.shape == "exp":
            # Exponential ease-in: (e^(k·t) − 1) / (e^k − 1), k=4
            k = 4.0
            if t == 0.0:
                return 0.0
            return (math.exp(k * t) - 1.0) / (math.exp(k) - 1.0)
        else:  # linear
            return t

    # ── Serialisation ─────────────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AutomationCurve":
        return cls(
            start=float(d.get("start", 0.0)),
            end=float(d.get("end", 0.0)),
            shape=str(d.get("shape", "linear")),
            enabled=bool(d.get("enabled", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "shape": self.shape,
            "enabled": self.enabled,
        }

    def __repr__(self) -> str:
        return (
            f"AutomationCurve(start={self.start}, end={self.end}, "
            f"shape={self.shape!r}, enabled={self.enabled})"
        )


# ── Per-preset automation structure ──────────────────────────────────────────

# Automatable per-layer parameters with (min, max) clamp ranges
LAYER_AUTO_PARAMS: dict[str, tuple[float, float]] = {
    "filter_cutoff":   (20.0,   20000.0),
    "fm_index":        (0.0,    5.0),
    "distortion_drive":(0.0,    5.0),
    "volume_db":       (-60.0,  6.0),
    "width":           (0.0,    2.0),
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


def parse_layer_automation(layer_cfg: dict) -> dict[str, AutomationCurve]:
    """Extract automation curves from a layer config dict."""
    result: dict[str, AutomationCurve] = {}
    auto_block = layer_cfg.get("automation") or {}
    for key in LAYER_AUTO_PARAMS:
        if key in auto_block and isinstance(auto_block[key], dict):
            curve = AutomationCurve.from_dict(auto_block[key])
            if curve.enabled:
                lo, hi = LAYER_AUTO_PARAMS[key]
                curve.start = max(lo, min(hi, curve.start))
                curve.end = max(lo, min(hi, curve.end))
                result[key] = curve
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
                curve.start = max(lo, min(hi, curve.start))
                curve.end = max(lo, min(hi, curve.end))
                result[key] = curve
    return result
