"""
engine/granular_layer.py
------------------------
Granular synthesis layer for MANTICE V17+.

New features:
  - pitch_semitones: manual ±24 st offset
  - sample_root_hz:  native pitch of the sample (auto from _PITCH_CACHE or user-specified)
  - pitch_mode:      resample | stretch | energetic
    - resample:  grain duration proportional to pitch (tape effect)
    - stretch:   pitch shifts but duration stays constant (OLA via double-resample)
    - energetic: resample pitch + positions snap to detected transient markers
"""

import os

import numpy as np
import soundfile as sf

from . import config

# Module-level pitch cache — populated by web_server at startup from pitch_cache.json
_PITCH_CACHE: dict = {}


def _detect_transients(audio: np.ndarray, sr: int, min_spacing_ms: float = 50.0) -> np.ndarray:
    """Energy-flux onset detection (numpy only). Returns sample positions of transients."""
    frame = 512
    hop = 256
    n_frames = (len(audio) - frame) // hop
    if n_frames < 4:
        return np.array([], dtype=int)
    rms = np.array([
        np.sqrt(np.mean(audio[i * hop: i * hop + frame] ** 2))
        for i in range(n_frames)
    ])
    flux = np.maximum(0.0, np.diff(rms))
    peak = flux.max()
    if peak < 1e-8:
        return np.array([], dtype=int)
    flux /= peak
    min_gap = max(1, int(min_spacing_ms * sr / 1000.0 / hop))
    peaks = []
    for i in range(1, len(flux) - 1):
        if flux[i] > 0.25:
            lo = max(0, i - min_gap)
            hi = min(len(flux), i + min_gap + 1)
            if flux[i] >= flux[lo:hi].max():
                peaks.append(i * hop)
    return np.array(peaks, dtype=int)


class StreamingGranularLayer:
    """Generates a cloud of overlapping grains from a source sample."""

    def __init__(self, cfg: dict, samples_dir: str, sample_rate: int = None):
        self.cfg = cfg
        self.mix = float(cfg.get("mix", 1.0))
        self._sr = sample_rate or config.SAMPLE_RATE

        # ── Load source sample ────────────────────────────────────────────────
        source_file = cfg.get("source", "singing_bowl.ogg")
        filepath = os.path.join(samples_dir, source_file)
        try:
            audio, sr = sf.read(filepath, dtype='float32')
        except Exception:
            filepath = os.path.join(samples_dir, "singing_bowl.ogg")
            source_file = "singing_bowl.ogg"
            audio, sr = sf.read(filepath, dtype='float32')

        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if sr != self._sr:
            ratio = self._sr / sr
            new_len = int(len(audio) * ratio)
            indices = np.linspace(0, len(audio) - 1, new_len)
            audio = np.interp(indices, np.arange(len(audio)), audio)

        self.source = audio.astype(np.float64)
        self.source_len = len(self.source)

        # ── Granular parameters ───────────────────────────────────────────────
        self.grain_size_ms = float(cfg.get("grain_size", 80))
        self.density = float(cfg.get("density", 15))
        self.pitch_spread = float(cfg.get("pitch_spread", 0.3))
        self.position = float(cfg.get("position", 0.5))
        self.scatter = float(cfg.get("scatter", 0.5))
        self.envelope = cfg.get("envelope", "hann")
        self.position_mode = cfg.get("position_mode", "linear")
        self.position_chaos = float(cfg.get("position_chaos", 0.3))

        # ── New pitch params ──────────────────────────────────────────────────
        self.pitch_mode = cfg.get("pitch_mode", "resample")  # resample | stretch | energetic
        pitch_semitones = float(cfg.get("pitch_semitones", 0.0))

        # Determine sample's native root Hz
        sample_root_hz = cfg.get("sample_root_hz") or _PITCH_CACHE.get(source_file)
        layer_root_hz = cfg.get("root")  # layer target root (may be None for granular)

        # Base pitch ratio: transposition toward layer root + manual semitone offset
        if sample_root_hz and layer_root_hz and sample_root_hz > 0 and layer_root_hz > 0:
            root_ratio = float(layer_root_hz) / float(sample_root_hz)
        else:
            root_ratio = 1.0
        self._base_ratio = root_ratio * (2.0 ** (pitch_semitones / 12.0))

        # ── Energetic: pre-compute transient markers ──────────────────────────
        if self.pitch_mode == "energetic":
            self._transient_markers = _detect_transients(self.source, self._sr)
        else:
            self._transient_markers = np.array([], dtype=int)

        # ── State ─────────────────────────────────────────────────────────────
        self._position_walk = self.position
        self._sample_counter = 0
        self._next_grain_at = 0
        self._active_grains = []
        self._schedule_next_grain()

    def _schedule_next_grain(self):
        if self.density <= 0:
            self._next_grain_at += self._sr * 100
            return
        interval = self._sr / self.density
        jitter = interval * 0.3 * (np.random.random() - 0.5)
        self._next_grain_at += int(interval + jitter)

    def _spawn_grain_at(self, start_in_chunk: int):
        grain_samples = int(self.grain_size_ms * self._sr / 1000)
        grain_samples = max(64, min(grain_samples, self.source_len - 1))

        # ── Position ──────────────────────────────────────────────────────────
        if self.position_mode == "random":
            step = np.random.normal(0, self.position_chaos * 0.04)
            self._position_walk = float(np.clip(self._position_walk + step, 0.05, 0.95))
            effective_position = self._position_walk
        else:
            effective_position = self.position

        if self.pitch_mode == "energetic" and len(self._transient_markers) > 0:
            # Snap to nearest transient, then scatter slightly around it
            center = int(effective_position * self.source_len)
            dists = np.abs(self._transient_markers - center)
            nearest = int(self._transient_markers[np.argmin(dists)])
            scatter_range = max(0, int(self.scatter * grain_samples * 2))
            offset = nearest + int(np.random.uniform(-scatter_range, scatter_range))
        else:
            center = int(effective_position * self.source_len)
            scatter_range = int(self.scatter * self.source_len * 0.5)
            offset = center + int(np.random.uniform(-scatter_range, scatter_range))

        offset = max(0, min(offset, self.source_len - grain_samples))
        grain = self.source[offset: offset + grain_samples].copy()
        original_len = grain_samples

        # ── Pitch ─────────────────────────────────────────────────────────────
        # Total ratio = base (root transposition + semitone offset) × random spread
        spread_st = np.random.normal(0, self.pitch_spread) if self.pitch_spread > 0 else 0.0
        total_ratio = self._base_ratio * (2.0 ** (spread_st / 12.0))

        if abs(total_ratio - 1.0) > 0.001 and total_ratio > 0:
            new_len = max(10, int(original_len / total_ratio))
            indices = np.linspace(0, len(grain) - 1, new_len)
            grain = np.interp(indices, np.arange(len(grain)), grain)

            if self.pitch_mode == "stretch":
                # Restore original grain duration (OLA-lite: resample back)
                indices2 = np.linspace(0, len(grain) - 1, original_len)
                grain = np.interp(indices2, np.arange(len(grain)), grain)
                grain_samples = original_len
            else:
                # resample / energetic: duration follows pitch (tape effect)
                grain_samples = new_len

        # ── Envelope ──────────────────────────────────────────────────────────
        if self.envelope == "triangle":
            env = np.concatenate([
                np.linspace(0, 1, grain_samples // 2),
                np.linspace(1, 0, grain_samples - grain_samples // 2),
            ])
        else:
            env = np.hanning(grain_samples)

        grain = grain[:grain_samples]  # safety clip
        grain *= env * np.random.uniform(0.6, 1.0)

        self._active_grains.append({
            'data': grain,
            'pos': 0,
            'length': grain_samples,
            'start_in_chunk': max(0, start_in_chunk),
        })

    def next_chunk(self, n_samples: int) -> np.ndarray:
        output = np.zeros(n_samples, dtype=np.float64)
        chunk_end = self._sample_counter + n_samples
        while self._next_grain_at < chunk_end:
            start_offset = self._next_grain_at - self._sample_counter
            self._spawn_grain_at(start_offset)
            self._schedule_next_grain()

        new_active = []
        for grain in self._active_grains:
            data = grain['data']
            pos = grain['pos']
            start_in_chunk = grain.get('start_in_chunk', 0)
            remaining = grain['length'] - pos
            available = min(remaining, n_samples - start_in_chunk)
            if available > 0:
                output[start_in_chunk: start_in_chunk + available] += data[pos: pos + available]
                grain['pos'] = pos + available
                grain['start_in_chunk'] = 0

            if grain['pos'] < grain['length']:
                new_active.append(grain)

        self._active_grains = new_active
        self._sample_counter = chunk_end
        return output * self.mix
