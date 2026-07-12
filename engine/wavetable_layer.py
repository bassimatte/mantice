"""Streaming wavetable oscillator for imported multi-frame WAV files."""

from pathlib import Path
import random

import numpy as np
import soundfile as sf


class StreamingWavetableLayer:
    """Polyphonic wavetable layer with smooth phase and frame interpolation."""

    def __init__(self, cfg: dict, samples_dir: str, sample_rate: int):
        self.SR = int(sample_rate)
        self.cfg = cfg
        self.frame_size = max(32, int(cfg.get("wavetable_frame_size", 2048)))
        source = str(cfg.get("wavetable_source") or "")
        if not source or ".." in source:
            raise ValueError("Wavetable source is missing or invalid")
        path = (Path(samples_dir) / source).resolve()
        samples_root = Path(samples_dir).resolve()
        if samples_root not in path.parents or not path.is_file():
            raise ValueError(f"Wavetable not found: {source}")

        audio, _ = sf.read(str(path), dtype="float32", always_2d=True)
        mono = np.mean(audio, axis=1, dtype=np.float32)
        if len(mono) < 32:
            raise ValueError("Wavetable WAV is too short")
        if len(mono) < self.frame_size:
            old_x = np.linspace(0.0, 1.0, len(mono), endpoint=False)
            new_x = np.linspace(0.0, 1.0, self.frame_size, endpoint=False)
            mono = np.interp(new_x, old_x, mono).astype(np.float32)

        frame_count = min(256, max(1, len(mono) // self.frame_size))
        table = mono[:frame_count * self.frame_size].reshape(frame_count, self.frame_size)
        table = table - np.mean(table, axis=1, keepdims=True)
        peak = float(np.max(np.abs(table)))
        self.table = (table / peak if peak > 1e-8 else table).astype(np.float32)
        self.frame_count = frame_count

        voices = max(1, min(12, int(cfg.get("voices", 3))))
        root = max(1.0, float(cfg.get("root", 110.0)))
        detune = max(0.0, float(cfg.get("wavetable_detune_cents", 7.0)))
        offsets = np.linspace(-detune, detune, voices, dtype=np.float32) if voices > 1 else np.zeros(1, dtype=np.float32)
        self.freqs = (root * np.power(2.0, offsets / 1200.0)).astype(np.float32)
        self.phases = np.array([random.random() for _ in range(voices)], dtype=np.float32)
        amp_min = float(cfg.get("amp_min", 0.01))
        amp_max = float(cfg.get("amp_max", 0.05))
        self.amplitudes = np.array([random.uniform(amp_min, amp_max) for _ in range(voices)], dtype=np.float32)
        self._gain = np.float32(10.0 ** (float(cfg.get("volume_db", 0.0)) / 20.0))

        self.position = float(np.clip(cfg.get("wavetable_position", 0.0), 0.0, 1.0))
        self.scan_start = float(np.clip(cfg.get("wavetable_scan_start", 0.0), 0.0, 1.0))
        self.scan_end = float(np.clip(cfg.get("wavetable_scan_end", 1.0), 0.0, 1.0))
        if self.scan_end < self.scan_start:
            self.scan_start, self.scan_end = self.scan_end, self.scan_start
        self.scan_rate = max(0.0, float(cfg.get("wavetable_scan_rate", 0.01)))
        self.scan_mode = str(cfg.get("wavetable_scan_mode", "pingpong"))
        self.scan_phase = 0.0

    def _frame_positions(self, n_samples: int) -> np.ndarray:
        if self.frame_count == 1 or self.scan_mode == "static" or self.scan_rate <= 0.0:
            return np.full(n_samples, self.position * (self.frame_count - 1), dtype=np.float32)
        phase = self.scan_phase + np.arange(n_samples, dtype=np.float32) * (self.scan_rate / self.SR)
        wrapped = phase % 1.0
        curve = 1.0 - np.abs(2.0 * wrapped - 1.0) if self.scan_mode == "pingpong" else wrapped
        self.scan_phase = float((phase[-1] + self.scan_rate / self.SR) % 1.0)
        normalized = self.scan_start + curve * (self.scan_end - self.scan_start)
        return normalized * np.float32(self.frame_count - 1)

    def next_chunk(self, n_samples: int) -> np.ndarray:
        frame_pos = self._frame_positions(n_samples)
        frame0 = np.floor(frame_pos).astype(np.int32)
        frame1 = np.minimum(frame0 + 1, self.frame_count - 1)
        frame_mix = frame_pos - frame0
        output = np.zeros(n_samples, dtype=np.float32)

        for voice, frequency in enumerate(self.freqs):
            phase = (self.phases[voice] + np.arange(n_samples, dtype=np.float32) * (frequency / self.SR)) % 1.0
            sample_pos = phase * self.frame_size
            sample0 = np.floor(sample_pos).astype(np.int32) % self.frame_size
            sample1 = (sample0 + 1) % self.frame_size
            sample_mix = sample_pos - np.floor(sample_pos)
            wave0 = self.table[frame0, sample0] * (1.0 - sample_mix) + self.table[frame0, sample1] * sample_mix
            wave1 = self.table[frame1, sample0] * (1.0 - sample_mix) + self.table[frame1, sample1] * sample_mix
            output += (wave0 * (1.0 - frame_mix) + wave1 * frame_mix) * self.amplitudes[voice]
            self.phases[voice] = np.float32((phase[-1] + frequency / self.SR) % 1.0)

        return output * self._gain
