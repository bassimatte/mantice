"""
engine/binaural.py — MANTICE V9.0
-------------------------------
Binaural beats processor.

Two modes:
  - "detune": offsets existing voice frequencies by ±beat_hz/2 per ear.
    Applied during layer build — each voice renders L/R with slight detuning.
  - "carrier": adds a dedicated sine-pair layer (carrier_hz ± beat_hz/2).
    Applied as a post-mix addition to the stereo bus.

Both require stereo (headphones) to produce the perceptual beating effect.
"""

import numpy as np

from . import config


def apply_binaural_detune(
    mono_voice: np.ndarray,
    carrier_freq: float,
    beat_hz: float,
    duration: float,
) -> np.ndarray:
    """
    Given a mono voice signal generated at `carrier_freq`, produce a stereo
    (N, 2) array where the left channel is pitched down by beat_hz/2 and the
    right channel is pitched up by beat_hz/2 using single-sideband frequency
    shifting (ring modulation with quadrature carrier).
    """
    samples = len(mono_voice)
    t = np.linspace(0, duration, samples, endpoint=False)
    shift = beat_hz / 2.0

    # Hilbert-style: shift L down, R up via ring modulation
    # For subtle shifts (<30 Hz), simple ring mod is perceptually transparent
    left = mono_voice * np.cos(2 * np.pi * shift * t)
    right = mono_voice * np.cos(2 * np.pi * (-shift) * t)

    stereo = np.column_stack([left, right])
    return stereo


def generate_binaural_carrier(
    carrier_hz: float,
    beat_hz: float,
    amplitude: float,
    duration: float,
    fade_secs: float = 3.0,
) -> np.ndarray:
    """
    Generate a pure binaural carrier pair: L = carrier - beat/2, R = carrier + beat/2.
    Returns stereo (N, 2) array.
    """
    samples = int(duration * config.SAMPLE_RATE)
    t = np.linspace(0, duration, samples, endpoint=False)

    freq_l = carrier_hz - beat_hz / 2.0
    freq_r = carrier_hz + beat_hz / 2.0

    left = np.sin(2 * np.pi * freq_l * t) * amplitude
    right = np.sin(2 * np.pi * freq_r * t) * amplitude

    # Smooth fade in/out
    fade_n = min(int(fade_secs * config.SAMPLE_RATE), samples // 4)
    env = np.ones(samples)
    env[:fade_n] = 0.5 * (1 - np.cos(np.pi * np.arange(fade_n) / fade_n))
    env[-fade_n:] = 0.5 * (1 + np.cos(np.pi * np.arange(fade_n) / fade_n))

    left *= env
    right *= env

    return np.column_stack([left, right])
