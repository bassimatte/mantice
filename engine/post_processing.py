"""
engine/post_processing.py
--------------------------
High-quality post-processing effects applied after synthesis.

Used by both web export and Python CLI to ensure consistent quality.
"""

import numpy as np


def oversampled_saturate(audio: np.ndarray, saturation: float, factor: int = 4) -> np.ndarray:
    """
    Apply tanh waveshaping at ``factor``× oversampling to eliminate in-band aliasing.

    Without oversampling, tanh generates harmonics above Nyquist that fold back
    into the audible band as inharmonic noise ("fizz"). At 4× we cut everything
    above the original Nyquist before decimating, reducing alias energy by >99%.

    Args:
        audio:      (N, 2) stereo float32 array at any sample rate.
        saturation: 0–1 drive amount (same scale as the engine param).
        factor:     Oversampling factor (4 is sufficient; cost ≈ 4× waveshaper math).

    Returns:
        Same shape as input, tanh-shaped without aliasing artefacts.
    """
    if saturation <= 0.01:
        return audio
    from scipy.signal import resample_poly, butter, sosfiltfilt
    drive = 1.0 + saturation * 3.0
    norm  = float(np.tanh(drive))
    n_in  = audio.shape[0]
    # 1. Upsample
    up = resample_poly(audio, factor, 1, axis=0)
    # 2. Waveshaper at oversampled rate
    up = np.tanh(up * drive) / norm
    # 3. Anti-image low-pass just below original Nyquist.
    #    sosfiltfilt (bidirectional, zero-phase) automatically pads edges so the
    #    filter starts from a stable state — avoids the click that sosfilt
    #    produces when the first sample is non-zero (zero initial-condition step).
    sos = butter(8, 0.9 / factor, output="sos")
    up  = sosfiltfilt(sos, up, axis=0)
    # 4. Decimate back to original rate
    out = resample_poly(up, 1, factor, axis=0)
    # Resample can introduce slight length mismatch (rounding)
    if out.shape[0] != n_in:
        out = out[:n_in]
    return out
