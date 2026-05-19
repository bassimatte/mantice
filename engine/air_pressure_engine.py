"""
engine/air_pressure_engine.py
------------------------------
Generates a slow-breathing atmospheric air-pressure layer.
Parameters come from the preset's 'air' section.
"""

import numpy as np

from . import config


class AirPressureEngine:

    @staticmethod
    def generate(
        duration:    float,
        intensity:   float = 0.12,
        movement:    float = 0.01,
        turbulence:  float = 0.04,
    ) -> np.ndarray:
        samples = int(duration * config.SAMPLE_RATE)
        t       = np.linspace(0, duration, samples, endpoint=False)

        # Ultra-slow atmospheric pressure wave
        pressure_wave = np.sin(2 * np.pi * movement * t)

        # Smoothed noise field (coloured noise, not white)
        noise  = np.random.randn(samples)
        kernel = int(0.1 * config.SAMPLE_RATE)           # 100 ms smoothing window
        smooth = np.convolve(noise, np.ones(kernel) / kernel, mode="same")

        air = smooth * turbulence + pressure_wave * 0.4

        # Slow evolving amplitude envelope (breathes in and out)
        breath_env = np.sin(2 * np.pi * 0.003 * t) * 0.5 + 0.5

        # Hard fade at edges to avoid clicks
        fade_n = min(int(3.0 * config.SAMPLE_RATE), samples // 4)
        edge   = np.ones(samples)
        edge[:fade_n]  = np.linspace(0, 1, fade_n)
        edge[-fade_n:] = np.linspace(1, 0, fade_n)

        return air * breath_env * intensity * edge
