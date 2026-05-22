"""Master bus EQ and compressor processing for offline and streaming audio."""

from __future__ import annotations

from copy import deepcopy
from math import cos, exp, pi, sin, sqrt
from typing import Any

import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi


_DEFAULT_ATTACK_MS  = 50.0
_DEFAULT_RELEASE_MS = 200.0
_DEFAULT_KNEE_DB    = 0.0   # 0 = hard knee; >0 = soft knee width in dB
_BASS_HZ  = 100.0
_MID_HZ   = 1000.0
_AIR_HZ   = 8000.0
_MID_Q    = 1.0


def _as_stereo(audio: np.ndarray) -> tuple[np.ndarray, np.dtype]:
    arr = np.asarray(audio)
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise ValueError("master processing expects stereo audio with shape (N, 2)")
    return arr.astype(np.float64, copy=True), arr.dtype


def _safe_fc(fc: float, sr: float) -> float:
    nyquist = sr * 0.5
    return float(min(max(fc, 1.0), nyquist * 0.999))


def _highpass_sos(fs: float, fc: float) -> np.ndarray:
    return butter(2, _safe_fc(fc, fs) / (fs * 0.5), btype="high", output="sos")


def _low_shelf_sos(fs: float, fc: float, gain_db: float) -> np.ndarray:
    A = 10 ** (gain_db / 40.0)
    w0 = 2.0 * pi * _safe_fc(fc, fs) / fs
    cw = cos(w0)
    sw = sin(w0)
    alpha = sw * sqrt(2.0) * 0.5
    sqrt_A = sqrt(A)
    b0 = A * ((A + 1.0) - (A - 1.0) * cw + 2.0 * sqrt_A * alpha)
    b1 = 2.0 * A * ((A - 1.0) - (A + 1.0) * cw)
    b2 = A * ((A + 1.0) - (A - 1.0) * cw - 2.0 * sqrt_A * alpha)
    a0 = (A + 1.0) + (A - 1.0) * cw + 2.0 * sqrt_A * alpha
    a1 = -2.0 * ((A - 1.0) + (A + 1.0) * cw)
    a2 = (A + 1.0) + (A - 1.0) * cw - 2.0 * sqrt_A * alpha
    return np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]], dtype=np.float64)


def _high_shelf_sos(fs: float, fc: float, gain_db: float) -> np.ndarray:
    A = 10 ** (gain_db / 40.0)
    w0 = 2.0 * pi * _safe_fc(fc, fs) / fs
    cw = cos(w0)
    sw = sin(w0)
    alpha = sw * sqrt(2.0) * 0.5
    sqrt_A = sqrt(A)
    b0 = A * ((A + 1.0) + (A - 1.0) * cw + 2.0 * sqrt_A * alpha)
    b1 = -2.0 * A * ((A - 1.0) + (A + 1.0) * cw)
    b2 = A * ((A + 1.0) + (A - 1.0) * cw - 2.0 * sqrt_A * alpha)
    a0 = (A + 1.0) - (A - 1.0) * cw + 2.0 * sqrt_A * alpha
    a1 = 2.0 * ((A - 1.0) - (A + 1.0) * cw)
    a2 = (A + 1.0) - (A - 1.0) * cw - 2.0 * sqrt_A * alpha
    return np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]], dtype=np.float64)


def _peaking_sos(fs: float, fc: float, gain_db: float, q: float) -> np.ndarray:
    A = 10 ** (gain_db / 40.0)
    w0 = 2.0 * pi * _safe_fc(fc, fs) / fs
    alpha = sin(w0) / (2.0 * q)
    cw = cos(w0)
    b0 = 1.0 + alpha * A
    b1 = -2.0 * cw
    b2 = 1.0 - alpha * A
    a0 = 1.0 + alpha / A
    a1 = -2.0 * cw
    a2 = 1.0 - alpha / A
    return np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]], dtype=np.float64)


def _build_filter_chain(master_cfg: dict[str, Any] | None, sr: float) -> list[np.ndarray]:
    master_cfg = master_cfg or {}
    eq = master_cfg.get("eq", {}) or {}
    filters: list[np.ndarray] = []

    low_cut_hz = float(eq.get("low_cut_hz", 20.0))
    if low_cut_hz > 22.0:
        filters.append(_highpass_sos(sr, low_cut_hz))

    bass_db = float(eq.get("bass_db", 0.0))
    if abs(bass_db) >= 0.1:
        filters.append(_low_shelf_sos(sr, _BASS_HZ, bass_db))

    mid_db = float(eq.get("mid_db", 0.0))
    if abs(mid_db) >= 0.1:
        filters.append(_peaking_sos(sr, _MID_HZ, mid_db, _MID_Q))

    air_db = float(eq.get("air_db", 0.0))
    if abs(air_db) >= 0.1:
        filters.append(_high_shelf_sos(sr, _AIR_HZ, air_db))

    return filters


def _compress_stereo(audio: np.ndarray, sr: float, comp_cfg: dict[str, Any] | None, env_state: float = 0.0) -> tuple[np.ndarray, float]:
    comp_cfg = comp_cfg or {}
    threshold_db = float(comp_cfg.get("threshold_db", 0.0))
    ratio        = float(comp_cfg.get("ratio", 2.0))
    makeup_db    = float(comp_cfg.get("makeup_db", 0.0))
    attack_ms    = float(comp_cfg.get("attack_ms",  _DEFAULT_ATTACK_MS))
    release_ms   = float(comp_cfg.get("release_ms", _DEFAULT_RELEASE_MS))
    knee_db      = float(comp_cfg.get("knee_db",    _DEFAULT_KNEE_DB))

    if ratio <= 1.01 and abs(makeup_db) < 0.1:
        return audio, float(env_state)

    threshold = 10 ** (threshold_db / 20.0)
    makeup    = 10 ** (makeup_db / 20.0)
    attack_coef  = exp(-1.0 / (max(attack_ms,  0.1) * 0.001 * sr))
    release_coef = exp(-1.0 / (max(release_ms, 1.0) * 0.001 * sr))
    level = np.max(np.abs(audio), axis=1)
    env   = np.empty_like(level)
    current = float(env_state)

    for i, sample_level in enumerate(level):
        coef = attack_coef if sample_level > current else release_coef
        current = coef * current + (1.0 - coef) * sample_level
        env[i] = current

    gain = np.ones_like(env)
    if ratio > 1.01:
        if knee_db > 0.1:
            # Soft knee: blend between unity gain and compressed gain
            # over a ±knee_db/2 window around threshold
            half_knee = knee_db / 2.0
            knee_lo = threshold * (10 ** (-half_knee / 20.0))
            knee_hi = threshold * (10 ** ( half_knee / 20.0))
            above   = env > threshold
            in_knee = (env >= knee_lo) & ~above
            if np.any(above):
                gain[above] = (threshold / np.maximum(env[above], 1e-12)) ** (1.0 - 1.0 / ratio)
            if np.any(in_knee):
                t = (env[in_knee] - knee_lo) / np.maximum(knee_hi - knee_lo, 1e-12)
                soft_ratio = 1.0 + (ratio - 1.0) * t
                gain[in_knee] = (threshold / np.maximum(env[in_knee], 1e-12)) ** (1.0 - 1.0 / soft_ratio)
        else:
            mask = env > threshold
            if np.any(mask):
                gain[mask] = (threshold / np.maximum(env[mask], 1e-12)) ** (1.0 - 1.0 / ratio)

    return audio * gain[:, None] * makeup, current


def apply_master_offline(audio: np.ndarray, sr: float, master_cfg: dict[str, Any] | None) -> np.ndarray:
    processed, out_dtype = _as_stereo(audio)

    for sos in _build_filter_chain(master_cfg, sr):
        processed[:, 0] = sosfilt(sos, processed[:, 0])
        processed[:, 1] = sosfilt(sos, processed[:, 1])

    processed, _ = _compress_stereo(processed, sr, (master_cfg or {}).get("comp", {}), 0.0)
    return processed.astype(out_dtype, copy=False)


class MasterProcessor:
    def __init__(self, master_cfg: dict[str, Any] | None, sr: float):
        self.master_cfg = deepcopy(master_cfg or {})
        self.sr = float(sr)
        self._filters = []
        for sos in _build_filter_chain(self.master_cfg, self.sr):
            self._filters.append({
                "sos": sos,
                "zi_l": sosfilt_zi(sos) * 0.0,
                "zi_r": sosfilt_zi(sos) * 0.0,
            })
        self._comp_cfg = deepcopy((self.master_cfg or {}).get("comp", {}) or {})
        self._comp_env = 0.0

    def process(self, chunk: np.ndarray) -> np.ndarray:
        processed, out_dtype = _as_stereo(chunk)

        for stage in self._filters:
            processed[:, 0], stage["zi_l"] = sosfilt(stage["sos"], processed[:, 0], zi=stage["zi_l"])
            processed[:, 1], stage["zi_r"] = sosfilt(stage["sos"], processed[:, 1], zi=stage["zi_r"])

        processed, self._comp_env = _compress_stereo(processed, self.sr, self._comp_cfg, self._comp_env)
        return processed.astype(out_dtype, copy=False)

    def copy_state(self) -> "MasterProcessor":
        clone = MasterProcessor(deepcopy(self.master_cfg), self.sr)
        for clone_stage, stage in zip(clone._filters, self._filters):
            clone_stage["zi_l"] = stage["zi_l"].copy()
            clone_stage["zi_r"] = stage["zi_r"].copy()
        clone._comp_env = float(self._comp_env)
        return clone
