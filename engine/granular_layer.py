"""
engine/granular_layer.py
------------------------
Granular synthesis layer for MANTICE V17.

Reads from audio sample files and generates a cloud of overlapping grains.
Compatible interface with StreamingLayer (next_chunk returns mono float array).
"""

import os

import numpy as np
import soundfile as sf

from . import config


class StreamingGranularLayer:
    """Generates a cloud of overlapping grains from a source sample."""

    def __init__(self, cfg: dict, samples_dir: str):
        self.cfg = cfg
        self.mix = float(cfg.get("mix", 1.0))

        # Load source sample
        source_file = cfg.get("source", "singing_bowl.ogg")
        filepath = os.path.join(samples_dir, source_file)
        audio, sr = sf.read(filepath, dtype='float32')

        # Convert to mono if stereo
        if audio.ndim > 1:
            audio = audio.mean(axis=1)

        # Resample if needed (simple linear interpolation)
        if sr != config.SAMPLE_RATE:
            ratio = config.SAMPLE_RATE / sr
            new_len = int(len(audio) * ratio)
            indices = np.linspace(0, len(audio) - 1, new_len)
            audio = np.interp(indices, np.arange(len(audio)), audio)

        self.source = audio.astype(np.float64)
        self.source_len = len(audio)

        # Granular parameters
        self.grain_size_ms = float(cfg.get("grain_size", 80))
        self.density = float(cfg.get("density", 15))
        self.pitch_spread = float(cfg.get("pitch_spread", 0.3))
        self.position = float(cfg.get("position", 0.5))
        self.scatter = float(cfg.get("scatter", 0.5))
        self.envelope = cfg.get("envelope", "hann")

        # State
        self._sample_counter = 0
        self._next_grain_at = 0
        self._active_grains = []
        self._schedule_next_grain()

    def _schedule_next_grain(self):
        """Schedule when the next grain should start."""
        if self.density <= 0:
            self._next_grain_at = self._next_grain_at + config.SAMPLE_RATE * 100
            return
        interval = config.SAMPLE_RATE / self.density
        jitter = interval * 0.3 * (np.random.random() - 0.5)
        self._next_grain_at = self._next_grain_at + int(interval + jitter)

    def _spawn_grain_at(self, start_in_chunk: int):
        """Create a new grain starting at offset within current chunk."""
        grain_samples = int(self.grain_size_ms * config.SAMPLE_RATE / 1000)
        grain_samples = max(64, min(grain_samples, self.source_len - 1))

        center = int(self.position * self.source_len)
        scatter_range = int(self.scatter * self.source_len * 0.5)
        offset = center + int(np.random.uniform(-scatter_range, scatter_range))
        offset = max(0, min(offset, self.source_len - grain_samples))

        grain = self.source[offset:offset + grain_samples].copy()

        # Pitch shift via resampling
        if self.pitch_spread > 0:
            semitones = np.random.normal(0, self.pitch_spread)
            ratio = 2.0 ** (semitones / 12.0)
            new_len = int(len(grain) / ratio)
            if new_len > 10:
                indices = np.linspace(0, len(grain) - 1, new_len)
                grain = np.interp(indices, np.arange(len(grain)), grain)
                grain_samples = new_len

        # Apply envelope
        if self.envelope == "triangle":
            env = np.concatenate([
                np.linspace(0, 1, grain_samples // 2),
                np.linspace(1, 0, grain_samples - grain_samples // 2)
            ])
        else:  # hann
            env = np.hanning(grain_samples)
        grain *= env * np.random.uniform(0.6, 1.0)

        self._active_grains.append({
            'data': grain,
            'pos': 0,
            'length': grain_samples,
            'start_in_chunk': max(0, start_in_chunk),
        })

    def next_chunk(self, n_samples: int) -> np.ndarray:
        """Generate next chunk of granular audio (mono), vectorized."""
        output = np.zeros(n_samples, dtype=np.float64)

        # Spawn grains that should start during this chunk
        chunk_end = self._sample_counter + n_samples
        while self._next_grain_at < chunk_end:
            start_offset = self._next_grain_at - self._sample_counter
            self._spawn_grain_at(start_offset)
            self._schedule_next_grain()

        # Render active grains (vectorized per grain)
        new_active = []
        for grain in self._active_grains:
            data = grain['data']
            pos = grain['pos']
            start_in_chunk = grain.get('start_in_chunk', 0)
            remaining = grain['length'] - pos

            # How many samples of this grain fit in this chunk
            available = min(remaining, n_samples - start_in_chunk)
            if available > 0:
                output[start_in_chunk:start_in_chunk + available] += data[pos:pos + available]
                grain['pos'] = pos + available
                grain['start_in_chunk'] = 0  # next chunk starts at 0

            if grain['pos'] < grain['length']:
                new_active.append(grain)

        self._active_grains = new_active
        self._sample_counter = chunk_end

        return output * self.mix
