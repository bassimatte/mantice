"""
engine/post_processing.py
--------------------------
High-quality post-processing effects applied after synthesis.

Used by both web export and Python CLI to ensure consistent quality.
"""

import numpy as np
from scipy.signal import lfilter


TRUE_PEAK_CEILING = 10.0 ** (-1.0 / 20.0)  # −1 dBFS
LIVE_PEAK_CEILING = 0.92
DEFAULT_LOUDNESS_TARGET = -18.0
DEFAULT_LIVE_LOUDNESS_TARGET = -20.0
MAX_LOUDNESS_GAIN_DB = 9.0


def _k_weighting_coefficients(sr: float) -> tuple[tuple[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]]:
    """Return the BS.1770 K-weighting shelf and high-pass biquads."""
    fs = float(sr)

    # Coefficients and topology used by ITU-R BS.1770 reference
    # implementations (the De Man high-shelf and RLB high-pass stages).
    shelf_f = 1681.974450955533
    shelf_g = 3.999843853973347
    shelf_q = 0.7071752369554196
    k = np.tan(np.pi * shelf_f / fs)
    vh = 10.0 ** (shelf_g / 20.0)
    vb = vh ** 0.4996667741545416
    a0 = 1.0 + k / shelf_q + k * k
    shelf_b = np.array([
        (vh + vb * k / shelf_q + k * k) / a0,
        2.0 * (k * k - vh) / a0,
        (vh - vb * k / shelf_q + k * k) / a0,
    ], dtype=np.float64)
    shelf_a = np.array([
        1.0,
        2.0 * (k * k - 1.0) / a0,
        (1.0 - k / shelf_q + k * k) / a0,
    ], dtype=np.float64)

    highpass_f = 38.13547087602444
    highpass_q = 0.5003270373238773
    k = np.tan(np.pi * highpass_f / fs)
    a0 = 1.0 + k / highpass_q + k * k
    highpass_b = np.array([1.0 / a0, -2.0 / a0, 1.0 / a0], dtype=np.float64)
    highpass_a = np.array([
        1.0,
        2.0 * (k * k - 1.0) / a0,
        (1.0 - k / highpass_q + k * k) / a0,
    ], dtype=np.float64)
    return (shelf_b, shelf_a), (highpass_b, highpass_a)


def _as_stereo_float(audio: np.ndarray) -> np.ndarray:
    arr = np.asarray(audio, dtype=np.float64)
    if arr.ndim == 1:
        arr = np.column_stack((arr, arr))
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise ValueError("loudness processing expects mono or stereo audio")
    return arr


def k_weight_audio(audio: np.ndarray, sr: float) -> np.ndarray:
    """Apply BS.1770 K-weighting to a complete mono or stereo buffer."""
    weighted = _as_stereo_float(audio).copy()
    for b, a in _k_weighting_coefficients(sr):
        weighted = lfilter(b, a, weighted, axis=0)
    return weighted


def integrated_loudness(audio: np.ndarray, sr: float) -> float:
    """Measure gated stereo integrated loudness in LUFS (BS.1770 style)."""
    if np.asarray(audio).size == 0:
        return float("-inf")

    weighted = k_weight_audio(audio, sr)
    block_size = max(1, int(round(0.400 * float(sr))))
    step_size = max(1, int(round(0.100 * float(sr))))
    if len(weighted) < block_size:
        blocks = [weighted]
    else:
        starts = range(0, len(weighted) - block_size + 1, step_size)
        blocks = [weighted[start:start + block_size] for start in starts]

    energies = np.array([
        float(np.sum(np.mean(np.square(block), axis=0)))
        for block in blocks
    ], dtype=np.float64)
    loudness = -0.691 + 10.0 * np.log10(np.maximum(energies, 1e-30))

    absolute = energies[loudness >= -70.0]
    if absolute.size == 0:
        return float("-inf")
    relative_gate = -0.691 + 10.0 * np.log10(np.mean(absolute)) - 10.0
    gated = energies[loudness >= max(-70.0, relative_gate)]
    if gated.size == 0:
        return float("-inf")
    return float(-0.691 + 10.0 * np.log10(np.mean(gated)))


def loudness_normalize(
    audio: np.ndarray,
    sr: float,
    target_lufs: float = DEFAULT_LOUDNESS_TARGET,
    max_gain_db: float = MAX_LOUDNESS_GAIN_DB,
    ceiling: float = TRUE_PEAK_CEILING,
) -> np.ndarray:
    """Apply one bounded loudness gain, followed by the true-peak ceiling."""
    if np.asarray(audio).size == 0:
        return audio
    measured = integrated_loudness(audio, sr)
    if not np.isfinite(measured):
        return final_limit_normalize(audio, ceiling=ceiling)
    gain_db = min(float(target_lufs) - measured, float(max_gain_db))
    gained = np.asarray(audio) * (10.0 ** (gain_db / 20.0))
    return final_limit_normalize(gained, ceiling=ceiling)


class StreamingLoudnessController:
    """Slow, bounded live loudness trim with per-chunk peak protection.

    The controller tracks K-weighted energy over several seconds. Upward gain
    moves deliberately slowly so it follows preset-level differences rather
    than individual swells; emergency peak reduction remains immediate.
    """

    def __init__(
        self,
        sr: float,
        target_lufs: float = DEFAULT_LIVE_LOUDNESS_TARGET,
        max_gain_db: float = MAX_LOUDNESS_GAIN_DB,
        ceiling: float = LIVE_PEAK_CEILING,
        initial_gain_db: float = 6.0,
    ):
        self.sr = float(sr)
        self.target_lufs = float(target_lufs)
        self.max_gain_db = float(max_gain_db)
        self.ceiling = float(ceiling)
        self.gain = 10.0 ** (min(float(initial_gain_db), self.max_gain_db) / 20.0)
        self.energy = None
        self._peak_envelope = 0.0
        self._peak_release = np.exp(-1.0 / (self.sr * 0.25))
        self._filters = []
        for b, a in _k_weighting_coefficients(self.sr):
            self._filters.append({
                "b": b,
                "a": a,
                "zi": np.zeros((max(len(a), len(b)) - 1, 2), dtype=np.float64),
            })

    def process(self, chunk: np.ndarray) -> np.ndarray:
        arr = _as_stereo_float(chunk)
        if arr.size == 0:
            return chunk

        weighted = arr
        for stage in self._filters:
            weighted, stage["zi"] = lfilter(
                stage["b"], stage["a"], weighted, axis=0, zi=stage["zi"]
            )

        duration = len(arr) / self.sr
        chunk_energy = float(np.sum(np.mean(np.square(weighted), axis=0)))
        if self.energy is None:
            self.energy = chunk_energy
        else:
            memory = np.exp(-duration / 3.0)
            self.energy = memory * self.energy + (1.0 - memory) * chunk_energy

        if self.energy > 1e-12:
            loudness = -0.691 + 10.0 * np.log10(self.energy)
            desired_db = min(self.target_lufs - loudness, self.max_gain_db)
            desired_gain = 10.0 ** (desired_db / 20.0)
        else:
            desired_gain = 1.0

        # Fast downward movement, slow upward movement.
        tau = 0.20 if desired_gain < self.gain else 8.0
        smoothing = np.exp(-duration / tau)
        end_gain = desired_gain + (self.gain - desired_gain) * smoothing
        gain_ramp = np.linspace(self.gain, end_gain, len(arr), dtype=np.float64)
        processed = arr * gain_ramp[:, np.newaxis]

        # Stateful sample-level peak protection. Scaling an entire hot chunk
        # made its first sample jump away from the previous chunk even when
        # the loud peak occurred much later. An instant-attack, exponential-
        # release envelope keeps protection continuous across arbitrary chunk
        # sizes while still respecting the live ceiling.
        sample_peaks = np.max(np.abs(processed), axis=1)
        powers = np.power(
            self._peak_release,
            np.arange(1, len(processed) + 1, dtype=np.float64),
        )
        normalized = sample_peaks / powers
        running = np.maximum.accumulate(
            np.concatenate(([self._peak_envelope], normalized))
        )[1:]
        peak_envelope = running * powers
        peak_gain = np.minimum(
            1.0,
            self.ceiling / np.maximum(peak_envelope, 1e-12),
        )
        processed *= peak_gain[:, np.newaxis]
        self._peak_envelope = float(peak_envelope[-1])
        self.gain = max(0.0, float(end_gain))
        return processed.astype(np.asarray(chunk).dtype, copy=False)

    def copy_state(self) -> "StreamingLoudnessController":
        clone = StreamingLoudnessController(
            self.sr, self.target_lufs, self.max_gain_db, self.ceiling, initial_gain_db=0.0
        )
        clone.gain = float(self.gain)
        clone.energy = None if self.energy is None else float(self.energy)
        clone._peak_envelope = float(self._peak_envelope)
        for clone_stage, stage in zip(clone._filters, self._filters):
            clone_stage["zi"] = stage["zi"].copy()
        return clone


def final_limit_normalize(
    audio: np.ndarray,
    ceiling: float = TRUE_PEAK_CEILING,
    factor: int = 4,
) -> np.ndarray:
    """Attenuate a full render when its oversampled true peak exceeds ceiling.

    Quiet renders are never boosted. A single gain factor is applied to the
    complete buffer, avoiding the pumping and attack lag of a dynamic limiter.
    """
    if audio.size == 0:
        return audio

    from scipy.signal import resample_poly

    upsampled = resample_poly(audio, factor, 1, axis=0)
    true_peak = float(np.max(np.abs(upsampled)))
    if true_peak > ceiling:
        audio = audio * (ceiling / true_peak)
    return np.clip(audio, -1.0, 1.0).astype(audio.dtype, copy=False)


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
