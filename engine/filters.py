"""
engine/filters.py
-----------------
Butterworth filters using sosfilt (second-order sections) instead of lfilter.
sosfilt is numerically stable at high orders, avoids the polynomial
coefficient overflow that lfilter can hit above order 4.
"""

import numpy as np
from scipy.signal import butter, sosfilt

from . import config


class Filters:

    @staticmethod
    def lowpass(audio: np.ndarray, cutoff: float, order: int = 4) -> np.ndarray:
        nyquist = config.SAMPLE_RATE * 0.5
        norm    = min(cutoff / nyquist, 0.999)
        sos     = butter(order, norm, btype="low", output="sos")
        return sosfilt(sos, audio)

    @staticmethod
    def highpass(audio: np.ndarray, cutoff: float, order: int = 4) -> np.ndarray:
        nyquist = config.SAMPLE_RATE * 0.5
        norm    = max(cutoff / nyquist, 0.001)
        sos     = butter(order, norm, btype="high", output="sos")
        return sosfilt(sos, audio)

    @staticmethod
    def bandpass(
        audio: np.ndarray,
        lowcut: float,
        highcut: float,
        order: int = 4,
    ) -> np.ndarray:
        nyquist = config.SAMPLE_RATE * 0.5
        low     = max(lowcut  / nyquist, 0.001)
        high    = min(highcut / nyquist, 0.999)
        if low >= high:
            return audio
        sos = butter(order, [low, high], btype="band", output="sos")
        return sosfilt(sos, audio)
