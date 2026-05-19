"""
engine/subharmonic_earth.py
---------------------------
Generates a tectonic sub-bass rumble layer.
Parameters come from the preset's 'earth' section.
"""

import numpy as np

from . import config


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

        earth = np.sin(2 * np.pi * (tectonic_frequency + wobble) * t)

        # Sub-octave pressure layer
        pressure_wave = np.sin(2 * np.pi * tectonic_frequency * 0.5 * t) * 0.6

        signal = earth * 0.7 + pressure_wave * 0.3

        # Smooth attack / release so it doesn't click
        fade_n = min(int(4.0 * config.SAMPLE_RATE), samples // 4)
        env    = np.ones(samples)
        env[:fade_n]  = np.linspace(0, 1, fade_n)
        env[-fade_n:] = np.linspace(1, 0, fade_n)

        return signal * pressure * env
