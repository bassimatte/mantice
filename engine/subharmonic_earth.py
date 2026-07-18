"""
engine/subharmonic_earth.py
---------------------------
Generates a tectonic sub-bass rumble layer.
Parameters come from the preset's 'earth' section.
"""

import numpy as np

from . import config


def shape_earth_wave(phase: np.ndarray) -> np.ndarray:
    """Shape Earth toward audible bass instead of an inaudible sub-octave.

    Earlier versions paired the configured tectonic frequency with a strong
    half-frequency component. At common settings that created 5--10 Hz energy:
    useful to a meter, but mostly inaudible and expensive in headroom. A quiet
    octave harmonic keeps the sense of pressure while moving that energy up.
    """
    return np.sin(phase) * 0.72 + np.sin(phase * 2.0) * 0.28


class SubharmonicEarth:

    @staticmethod
    def generate(
        duration:            float,
        tectonic_frequency:  float = 18.0,
        pressure:            float = 0.4,
        movement:            float = 0.02,
    ) -> np.ndarray:
        samples = int(duration * config.SAMPLE_RATE)
        t       = np.linspace(0, duration, samples, endpoint=False)

        # Slow tectonic wobble on the fundamental pitch
        wobble = np.sin(2 * np.pi * movement * t) * 0.5

        phase = 2 * np.pi * (tectonic_frequency + wobble) * t
        signal = shape_earth_wave(phase)

        # Smooth attack / release so it doesn't click
        fade_n = min(int(4.0 * config.SAMPLE_RATE), samples // 4)
        env    = np.ones(samples)
        env[:fade_n]  = np.linspace(0, 1, fade_n)
        env[-fade_n:] = np.linspace(1, 0, fade_n)

        return signal * pressure * env
