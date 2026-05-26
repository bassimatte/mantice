"""
engine/journey.py — Preset Journey renderer for Mantice.

Renders a sequence of presets with smooth s-curve audio crossfades between
them. Walk automation runs normally during hold windows; morph windows use
audio-level crossfade so any preset combination is compatible.
"""

from __future__ import annotations

import numpy as np

from . import config
from .streaming_engine import StreamingDroneEngine
from .preset_loader import load_preset as _load_preset_file

SR = config.STREAM_SAMPLE_RATE
_CHUNK = 2048


# ── Audio helpers ─────────────────────────────────────────────────────────────

def _render_n_samples(engine: StreamingDroneEngine, n: int) -> np.ndarray:
    """Pull n samples from engine. Returns (n, 2) float32."""
    chunks, rem = [], n
    while rem > 0:
        k = min(_CHUNK, rem)
        chunks.append(engine.next_chunk(k))
        rem -= k
    return np.concatenate(chunks, axis=0).astype(np.float32)


def _scurve(n: int) -> np.ndarray:
    """Smooth-step fade 0→1 of length n, shape (n, 1)."""
    if n <= 0:
        return np.zeros((0, 1), dtype=np.float32)
    t = np.linspace(0.0, 1.0, n, endpoint=False, dtype=np.float32)
    return (t * t * (3.0 - 2.0 * t))[:, np.newaxis]


def _crossfade(engine_a: StreamingDroneEngine,
               engine_b: StreamingDroneEngine,
               morph_s: float) -> np.ndarray:
    """S-curve crossfade from engine_a to engine_b over morph_s seconds."""
    n = int(morph_s * SR)
    if n <= 0:
        return np.zeros((0, 2), dtype=np.float32)
    fade  = _scurve(n)
    audio_a = np.clip(_render_n_samples(engine_a, n), -1.0, 1.0)
    audio_b = np.clip(_render_n_samples(engine_b, n), -1.0, 1.0)
    return (audio_a * (1.0 - fade) + audio_b * fade).astype(np.float32)


# ── Engine factory ────────────────────────────────────────────────────────────

def _make_engine(preset: dict, seed: int, duration_s: float) -> StreamingDroneEngine:
    """Create a render-mode engine for a hold window."""
    p = dict(preset)
    p["duration"] = max(float(duration_s), 1.0)
    return StreamingDroneEngine(p, seed=seed, render_mode=True)


# ── Step expansion ────────────────────────────────────────────────────────────

def _expand_steps(steps: list[dict], loop: str) -> list[dict]:
    """Expand steps for loop / pingpong modes."""
    if len(steps) < 2:
        return list(steps)
    if loop == "loop":
        # After last step: morph back to first (no hold at the synthetic tail)
        tail = dict(steps[0])
        tail["hold_s"] = 0.0
        tail["morph_s"] = steps[-1].get("morph_s", 30.0)
        return list(steps) + [tail]
    if loop == "pingpong":
        return list(steps) + list(reversed(steps[:-1]))
    return list(steps)


# ── Preset loading ────────────────────────────────────────────────────────────

def _resolve_steps(expanded: list[dict]) -> list[tuple[dict, dict]]:
    """Resolve preset dict for each step. Returns [(step, preset_dict), ...]."""
    result = []
    for step in expanded:
        if "preset" in step and isinstance(step["preset"], dict):
            result.append((step, step["preset"]))
        else:
            path = step.get("preset_path") or step.get("preset_name", "")
            preset = _load_preset_file(path)
            result.append((step, preset))
    return result


# ── Main render ───────────────────────────────────────────────────────────────

def render_journey(
    steps: list[dict],
    loop: str = "none",
    seed: int = 42,
    max_samples: int | None = None,
) -> np.ndarray:
    """
    Render a preset journey to a single stereo float32 array.

    Parameters
    ----------
    steps
        List of dicts: { preset_path: str, hold_s: float, morph_s: float }
        ``preset_path`` is passed to ``load_preset()``.
    loop
        ``"none"`` — play once and stop.
        ``"loop"`` — crossfade back to step 0 after the last step.
        ``"pingpong"`` — play forward then backward (①②③②①).
    seed
        Shared random seed for all engines.
    max_samples
        If set, rendering stops after this many samples (for preview).

    Returns
    -------
    np.ndarray, shape (N, 2), dtype float32
    """
    if not steps:
        raise ValueError("Journey must have at least one step")

    expanded = _expand_steps(steps, loop)
    resolved = _resolve_steps(expanded)

    chunks: list[np.ndarray] = []
    n_steps = len(resolved)
    written = 0

    for i, (step, preset) in enumerate(resolved):
        hold_s  = float(step.get("hold_s", 60.0))
        morph_s = float(step.get("morph_s", 0.0))
        is_last = (i == n_steps - 1)

        engine_a = _make_engine(preset, seed, hold_s + morph_s)

        # Hold window
        if hold_s > 0.0:
            n_hold = int(hold_s * SR)
            if max_samples is not None:
                n_hold = min(n_hold, max_samples - written)
            if n_hold > 0:
                raw = _render_n_samples(engine_a, n_hold)
                chunks.append(np.clip(raw, -1.0, 1.0).astype(np.float32))
                written += n_hold
            if max_samples is not None and written >= max_samples:
                break

        # Morph window (not for last step)
        if morph_s > 0.0 and not is_last:
            _, next_preset = resolved[i + 1]
            engine_b = _make_engine(next_preset, seed, morph_s)
            n_morph = int(morph_s * SR)
            if max_samples is not None:
                n_morph = min(n_morph, max_samples - written)
            if n_morph > 0:
                chunks.append(_crossfade(engine_a, engine_b, n_morph / SR))
                written += n_morph
            if max_samples is not None and written >= max_samples:
                break

    if not chunks:
        return np.zeros((0, 2), dtype=np.float32)
    return np.concatenate(chunks, axis=0).astype(np.float32)


def journey_total_seconds(steps: list[dict], loop: str = "none") -> float:
    """Compute the total duration in seconds for a journey."""
    expanded = _expand_steps(steps, loop)
    n = len(expanded)
    total = 0.0
    for i, step in enumerate(expanded):
        total += float(step.get("hold_s", 0.0))
        if i < n - 1:
            total += float(step.get("morph_s", 0.0))
    return total
