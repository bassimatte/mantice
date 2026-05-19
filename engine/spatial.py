"""
engine/spatial.py
-----------------
Per-layer stereo placement using the quadrant and trajectory fields
that were previously read from presets but completely ignored.

pan_layer()   -- places a mono layer into stereo space
add_depth()   -- applies a global reverb-like depth wash to the mix
"""

import numpy as np

from . import config
from .filters import Filters

# Base pan position (0 = hard left, 1 = hard right) per quadrant
_QUADRANT_PAN = {
    "front_left":  0.18,
    "front_right": 0.82,
    "rear_left":   0.25,
    "rear_right":  0.75,
    "center":      0.50,
}

# Whether the quadrant implies rear-of-field depth treatment
_REAR_QUADRANTS = {"rear_left", "rear_right"}


def _delay_safe(audio: np.ndarray, delay_samples: int) -> np.ndarray:
    """Delay without extending the array length."""
    if delay_samples <= 0:
        return audio
    out = np.zeros_like(audio)
    out[delay_samples:] = audio[: len(audio) - delay_samples]
    return out


def pan_layer(
    mono:         np.ndarray,
    quadrant:     str,
    trajectory_x: str,
    trajectory_y: str,
    speed:        float,
) -> np.ndarray:
    """
    Take a mono layer signal and return a stereo (N, 2) array positioned
    according to the layer's spatial_motion parameters.

    quadrant    → base left/right position
    trajectory_x → pan automation over time
    trajectory_y → depth (distance) automation
    speed       → LFO frequency for trajectory (Hz)
    """
    samples = len(mono)
    t       = np.linspace(0, samples / config.SAMPLE_RATE, samples, endpoint=False)

    base_pan = _QUADRANT_PAN.get(quadrant, 0.5)

    # ── pan automation (trajectory_x) ──────────────────────────────────────
    if trajectory_x == "orbit":
        # Smooth circular motion — full 0→1 sweep
        pan = base_pan + np.sin(2 * np.pi * speed * t) * 0.32

    elif trajectory_x == "pendulum":
        # Side-to-side oscillation centred on base_pan
        pan = base_pan + np.sin(2 * np.pi * speed * t) * 0.25

    elif trajectory_x == "drift":
        # Two slow sine waves at inharmonic ratio — natural wandering
        pan = (
            base_pan
            + np.sin(2 * np.pi * speed       * t) * 0.12
            + np.sin(2 * np.pi * speed * 1.7 * t) * 0.08
        )

    elif trajectory_x == "spiral":
        # Amplitude-increasing orbit — starts narrow, widens over time
        depth = np.linspace(0.05, 0.38, samples)
        pan   = base_pan + np.sin(2 * np.pi * speed * t) * depth

    else:  # "none"
        pan = np.full(samples, base_pan)

    pan = np.clip(pan, 0.0, 1.0)

    # ── equal-power panning ─────────────────────────────────────────────────
    angle      = pan * (np.pi / 2)
    gain_left  = np.cos(angle)
    gain_right = np.sin(angle)

    # ── depth / distance (trajectory_y or rear quadrant) ───────────────────
    is_rear  = quadrant in _REAR_QUADRANTS
    add_depth = is_rear or trajectory_y in ("depth", "spiral")

    if add_depth:
        # Simulate rear-field distance: LPF + small delay + level reduction
        delay_n  = int(0.022 * config.SAMPLE_RATE)   # ~22 ms inter-aural smear
        lp_mono  = Filters.lowpass(mono, 3200)
        distant  = _delay_safe(lp_mono, delay_n) * 0.72
        src      = mono * 0.55 + distant * 0.45
    else:
        src = mono

    left  = src * gain_left
    right = src * gain_right

    return np.stack([left, right], axis=1)


def add_depth(stereo: np.ndarray, depth: float, wet: float) -> np.ndarray:
    """
    Global depth wash applied to the full stereo mix.
    Simulates room / air / distance on top of the per-layer panning.

    depth  → controls delay times (and therefore perceived room size)
    wet    → dry/wet balance
    """
    if wet <= 0.0:
        return stereo

    samples = len(stereo)
    mono    = stereo.mean(axis=1)

    # Three delay taps at different depths — creates a sense of space
    mid  = _delay_safe(Filters.lowpass(mono, 3200), int(0.04 * depth * config.SAMPLE_RATE)) * 0.45
    far  = _delay_safe(Filters.lowpass(mono, 1600), int(0.11 * depth * config.SAMPLE_RATE)) * 0.28
    rear = _delay_safe(Filters.lowpass(mono,  900), int(0.20 * depth * config.SAMPLE_RATE)) * 0.18

    depth_L = mid + rear
    depth_R = far + rear

    depth_stereo = np.stack([depth_L, depth_R], axis=1)

    return stereo * (1.0 - wet) + depth_stereo * wet
