"""Regression tests for the infrasonic headroom repair."""

import unittest

import numpy as np

from engine.master_processing import apply_master_offline
from engine.subharmonic_earth import SubharmonicEarth


def _tone(freq: float, seconds: float = 4.0, sr: int = 22050) -> np.ndarray:
    t = np.arange(int(seconds * sr), dtype=np.float64) / sr
    mono = np.sin(2.0 * np.pi * freq * t)
    return np.column_stack((mono, mono))


def _rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(audio))))


class LowFrequencyHeadroomTests(unittest.TestCase):
    def test_default_twenty_hz_low_cut_is_active(self):
        cfg = {
            "eq": {"low_cut_hz": 20.0},
            "comp": {"threshold_db": 0.0, "ratio": 1.0, "makeup_db": 0.0},
            "output_gain_db": 0.0,
        }
        ten_hz_source = _tone(10.0)
        eighty_hz_source = _tone(80.0)
        ten_hz = apply_master_offline(ten_hz_source, 22050, cfg)
        eighty_hz = apply_master_offline(eighty_hz_source, 22050, cfg)

        self.assertLess(_rms(ten_hz) / _rms(ten_hz_source), 0.27)
        self.assertGreater(_rms(eighty_hz) / _rms(eighty_hz_source), 0.98)

    def test_earth_no_longer_generates_a_sub_octave(self):
        earth = SubharmonicEarth.generate(
            duration=8.0,
            tectonic_frequency=12.0,
            pressure=1.0,
            movement=0.0,
        )
        spectrum = np.abs(np.fft.rfft(earth))
        freqs = np.fft.rfftfreq(len(earth), 1.0 / 22050)

        def magnitude_at(freq: float) -> float:
            return float(spectrum[np.argmin(np.abs(freqs - freq))])

        self.assertLess(magnitude_at(6.0), magnitude_at(24.0) * 0.01)
        self.assertGreater(magnitude_at(24.0), magnitude_at(12.0) * 0.25)


if __name__ == "__main__":
    unittest.main()
