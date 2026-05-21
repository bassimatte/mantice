"""
engine/streaming_engine.py
--------------------------
Chunk-based streaming drone engine for real-time preview.

Maintains internal state (oscillator phases, filter memories)
across calls to next_chunk(), enabling low-latency audio streaming.

Supports:
  - Infinite mode (no fixed duration — runs until stopped)
  - Hot-reload (swap preset mid-stream with crossfade)
"""

import os
import random
from typing import Optional, Callable

import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi

from . import config
from .granular_layer import StreamingGranularLayer
from .master_processing import MasterProcessor

# Use lower sample rate for real-time streaming (less CPU)
SR = config.STREAM_SAMPLE_RATE


# ── Stateful voice ────────────────────────────────────────────────────────────

class StreamingVoice:
    """A single FM voice that generates audio in chunks with continuous phase."""

    def __init__(
        self,
        carrier_freq: float,
        mod_ratio:    float,
        fm_index:     float,
        amplitude:    float,
        drift:        float,
        drift_rate:   float,
    ):
        self.carrier_freq = carrier_freq
        self.mod_freq     = carrier_freq * mod_ratio
        self.fm_index     = fm_index
        self.amplitude    = amplitude
        self.drift        = drift
        self.drift_rate   = drift_rate

        # Phase accumulators (continuous across chunks)
        self.carrier_phase = random.uniform(0, 2 * np.pi)
        self.mod_phase     = 0.0
        self.drift_phase   = random.uniform(0, 2 * np.pi)

    def next_chunk(self, n_samples: int) -> np.ndarray:
        dt = 1.0 / SR
        t  = np.arange(n_samples) * dt

        # Modulator
        mod_phases = self.mod_phase + 2 * np.pi * self.mod_freq * np.cumsum(np.ones(n_samples) * dt)
        modulator  = np.sin(mod_phases)
        self.mod_phase = mod_phases[-1] % (2 * np.pi)

        # Drift signal
        drift_phases = self.drift_phase + 2 * np.pi * self.drift_rate * np.cumsum(np.ones(n_samples) * dt)
        drift_signal = np.sin(drift_phases) * self.drift
        self.drift_phase = drift_phases[-1] % (2 * np.pi)

        # Carrier with FM + drift
        inst_freq    = self.carrier_freq * (1.0 + drift_signal)
        phase_inc    = 2 * np.pi * inst_freq * dt
        carrier_phases = self.carrier_phase + np.cumsum(phase_inc)
        signal = np.sin(carrier_phases + modulator * self.fm_index)
        self.carrier_phase = carrier_phases[-1] % (2 * np.pi)

        return signal * self.amplitude


# ── Stateful layer ────────────────────────────────────────────────────────────

class StreamingLayer:
    """A layer containing multiple streaming voices with band filtering.
    
    Voices are vectorized: all computed simultaneously using 2D arrays
    for real-time performance with high voice counts.
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        n_voices = cfg["voices"]

        # Vectorized voice parameters (shape: n_voices,)
        ratios = [random.choice(cfg["ratios"]) for _ in range(n_voices)]
        fm_ratios = [random.choice(cfg["fm_ratios"]) for _ in range(n_voices)]

        self.carrier_freqs = np.array([cfg["root"] * r for r in ratios], dtype=np.float32)
        self.mod_freqs = self.carrier_freqs * np.array(fm_ratios, dtype=np.float32)
        self.fm_indices = np.full(n_voices, cfg["fm_index"], dtype=np.float32)
        self.amplitudes = np.array([random.uniform(cfg["amp_min"], cfg["amp_max"]) for _ in range(n_voices)], dtype=np.float32)
        self.drifts = np.full(n_voices, cfg["drift"], dtype=np.float32)
        self.drift_rates = np.array([random.uniform(0.001, 0.006) for _ in range(n_voices)], dtype=np.float32)

        # Phase accumulators (shape: n_voices,)
        self.carrier_phases = np.array([random.uniform(0, 2 * np.pi) for _ in range(n_voices)], dtype=np.float32)
        self.mod_phases = np.zeros(n_voices, dtype=np.float32)
        self.drift_phases = np.array([random.uniform(0, 2 * np.pi) for _ in range(n_voices)], dtype=np.float32)

        # Precomputed angular frequencies
        self._mod_omega = np.float32(2 * np.pi) * self.mod_freqs
        self._drift_omega = np.float32(2 * np.pi) * self.drift_rates
        self._two_pi_dt = np.float32(2 * np.pi / SR)

        # Harmonic overtones
        self.harmonics = int(cfg.get("harmonics", 4))
        self.harmonic_decay = float(cfg.get("harmonic_decay", 0.7))

        # Filtered noise (breath texture)
        self.noise_amount = float(cfg.get("noise_amount", 0.0))
        self.noise_color = cfg.get("noise_color", "pink")
        self._noise_state = np.float32(0.0)  # 1-pole filter state for pink noise
        self._brown_state = np.float32(0.0)  # integrator state for brown noise

        # Band filter
        self._setup_filter(cfg.get("band", "mid"))

    def _setup_filter(self, band: str) -> None:
        nyquist = SR * 0.5
        order = 4
        if band == "sub":
            self.sos = butter(order, min(140 / nyquist, 0.999), btype="low", output="sos")
        elif band == "high":
            low  = max(1500 / nyquist, 0.001)
            high = min(7000 / nyquist, 0.999)
            self.sos = butter(order, [low, high], btype="band", output="sos")
        else:  # mid
            low  = max(140  / nyquist, 0.001)
            high = min(1500 / nyquist, 0.999)
            self.sos = butter(order, [low, high], btype="band", output="sos")

        self.zi = sosfilt_zi(self.sos) * 0.0

    def next_chunk(self, n_samples: int) -> np.ndarray:
        dt = np.float32(1.0 / SR)
        n_voices = len(self.carrier_freqs)

        # Precompute sample indices once (float32 for speed)
        samples = np.arange(n_samples, dtype=np.float32) * dt

        # Modulator: constant-frequency oscillators
        mod_phases = self.mod_phases[:, None] + (self._mod_omega[:, None] * samples[None, :])
        modulator = np.sin(mod_phases, dtype=np.float32)
        self.mod_phases = (mod_phases[:, -1] + self._mod_omega * dt) % (2 * np.pi)

        # Drift: slow LFO
        drift_phases = self.drift_phases[:, None] + (self._drift_omega[:, None] * samples[None, :])
        drift_signal = np.sin(drift_phases, dtype=np.float32) * self.drifts[:, None]
        self.drift_phases = (drift_phases[:, -1] + self._drift_omega * dt) % (2 * np.pi)

        # Carrier with FM + drift
        inst_freq = self.carrier_freqs[:, None] * (1.0 + drift_signal)
        phase_inc = self._two_pi_dt * inst_freq
        carrier_phases = self.carrier_phases[:, None] + np.cumsum(phase_inc, axis=1)

        # Fundamental signal
        signal = np.sin(carrier_phases + modulator * self.fm_indices[:, None], dtype=np.float32)

        # Harmonic overtones — loop over harmonics (max 8), each vectorized
        if self.harmonics > 1:
            for h in range(2, self.harmonics + 1):
                harmonic_signal = np.sin(
                    carrier_phases * h + modulator * self.fm_indices[:, None] * (1.0 / h),
                    dtype=np.float32
                )
                signal += harmonic_signal * (self.harmonic_decay ** (h - 1))
            # Normalize so amplitude stays consistent regardless of harmonic count
            norm = 1.0 + sum(self.harmonic_decay ** (h - 1) for h in range(2, self.harmonics + 1))
            signal /= norm

        self.carrier_phases = carrier_phases[:, -1] % (2 * np.pi)

        # Weighted sum via dot product
        layer = np.dot(self.amplitudes, signal)

        # Filtered noise (breath texture) — applied before band filter
        if self.noise_amount > 0.0:
            noise = self._generate_noise(n_samples)
            amp_scale = np.mean(self.amplitudes)
            layer = layer * (1.0 - self.noise_amount) + noise * self.noise_amount * amp_scale

        # Apply band filter
        filtered, self.zi = sosfilt(self.sos, layer, zi=self.zi)
        return filtered * self.cfg["mix"]

    def _generate_noise(self, n_samples: int) -> np.ndarray:
        """Generate colored noise (white, pink, or brown)."""
        white = np.random.randn(n_samples).astype(np.float32)
        if self.noise_color == "white":
            return white
        elif self.noise_color == "brown":
            # Brown noise: integrated white noise with HPF to prevent DC drift
            out = np.empty(n_samples, dtype=np.float32)
            state = self._brown_state
            for i in range(n_samples):
                state = state * 0.998 + white[i] * 0.02
                out[i] = state
            self._brown_state = state
            # Normalize
            peak = np.max(np.abs(out))
            if peak > 0.001:
                out /= peak
            return out
        else:
            # Pink noise: 1-pole lowpass approximation (simple and efficient)
            out = np.empty(n_samples, dtype=np.float32)
            state = self._noise_state
            alpha = np.float32(0.06)  # ~1/f characteristic
            for i in range(n_samples):
                state = state * np.float32(0.94) + white[i] * alpha
                out[i] = state
            self._noise_state = state
            # Normalize
            peak = np.max(np.abs(out))
            if peak > 0.001:
                out /= peak
            return out


class StreamingSubtractiveLayer:
    """
    Subtractive synthesis layer: waveform oscillators (saw/square/triangle)
    with optional dual-oscillator detune and sub-oscillator.
    Classic Reese bass and other filter-based drone textures.
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        n_voices = max(1, int(cfg.get("voices", 2)))
        self.waveform = cfg.get("waveform", "saw")
        self.root = float(cfg.get("root", 110.0))
        self.detune_cents = float(cfg.get("detune_cents", 8.0))
        self.sub_mix = float(cfg.get("sub_mix", 0.3))
        self.amp_min = float(cfg.get("amp_min", 0.01))
        self.amp_max = float(cfg.get("amp_max", 0.06))
        self.drift = float(cfg.get("drift", 0.002))

        ratios = cfg.get("ratios", [1.0])
        self.osc1_freqs = np.array([
            self.root * random.choice(ratios) * (2 ** (self.detune_cents / 1200))
            for _ in range(n_voices)
        ], dtype=np.float32)
        self.osc2_freqs = np.array([
            self.root * random.choice(ratios) * (2 ** (-self.detune_cents / 1200))
            for _ in range(n_voices)
        ], dtype=np.float32)
        self.sub_freq = self.root * 0.5

        self.amplitudes = np.array([
            random.uniform(self.amp_min, self.amp_max)
            for _ in range(n_voices)
        ], dtype=np.float32)

        self.osc1_phases = np.array([
            random.uniform(0, 2 * np.pi)
            for _ in range(n_voices)
        ], dtype=np.float32)
        self.osc2_phases = np.array([
            random.uniform(0, 2 * np.pi)
            for _ in range(n_voices)
        ], dtype=np.float32)
        self.sub_phase = random.uniform(0, 2 * np.pi)

        self.drift_phases = np.array([
            random.uniform(0, 2 * np.pi)
            for _ in range(n_voices)
        ], dtype=np.float32)
        self.drift_rates = np.array([
            random.uniform(0.001, 0.005)
            for _ in range(n_voices)
        ], dtype=np.float32)

    def _waveform(self, phases: np.ndarray) -> np.ndarray:
        """Generate waveform samples from phase array (0..2pi)."""
        p = phases % (2 * np.pi)
        if self.waveform == "square":
            return np.where(p < np.pi, np.float32(1.0), np.float32(-1.0)).astype(np.float32)
        if self.waveform == "triangle":
            return (
                np.float32(2.0)
                * np.abs(p / np.pi - np.floor(p / np.pi + np.float32(0.5)))
                * np.float32(2.0)
                - np.float32(1.0)
            ).astype(np.float32)
        return (p / np.pi - np.float32(1.0)).astype(np.float32)

    def next_chunk(self, n_samples: int) -> np.ndarray:
        dt = np.float32(1.0 / SR)
        t = np.arange(n_samples, dtype=np.float32) * dt

        drift_phases = self.drift_phases[:, None] + (2 * np.pi * self.drift_rates[:, None] * t[None, :])
        drift = np.sin(drift_phases, dtype=np.float32) * self.drift
        self.drift_phases = drift_phases[:, -1] % (2 * np.pi)

        inst_freq1 = self.osc1_freqs[:, None] * (1.0 + drift)
        phase_inc1 = 2 * np.pi * inst_freq1 * dt
        osc1_phases = self.osc1_phases[:, None] + np.cumsum(phase_inc1, axis=1)
        sig1 = self._waveform(osc1_phases)
        self.osc1_phases = osc1_phases[:, -1] % (2 * np.pi)

        inst_freq2 = self.osc2_freqs[:, None] * (1.0 + drift)
        phase_inc2 = 2 * np.pi * inst_freq2 * dt
        osc2_phases = self.osc2_phases[:, None] + np.cumsum(phase_inc2, axis=1)
        sig2 = self._waveform(osc2_phases)
        self.osc2_phases = osc2_phases[:, -1] % (2 * np.pi)

        combined = np.dot(self.amplitudes, (sig1 + sig2) * 0.5)

        sub_phases = self.sub_phase + 2 * np.pi * self.sub_freq * np.cumsum(np.ones(n_samples, dtype=np.float32) * dt)
        sub = np.sin(sub_phases, dtype=np.float32) * np.mean(self.amplitudes)
        self.sub_phase = sub_phases[-1] % (2 * np.pi)

        layer = combined * (1.0 - self.sub_mix) + sub * self.sub_mix
        return layer * self.cfg.get("mix", 1.0)


# ── Stateful spatial panner ───────────────────────────────────────────────────

class StreamingPanner:
    """Per-layer stereo panner with continuous trajectory and elevation."""

    _QUADRANT_PAN = {
        "front_left": 0.18, "front_right": 0.82,
        "rear_left": 0.25, "rear_right": 0.75, "center": 0.50,
    }

    def __init__(self, quadrant: str, trajectory_x: str, speed: float,
                 elevation: float = 0.0, elevation_motion: str = "static",
                 elevation_speed: float = 0.1, elevation_range: float = 60.0):
        self.base_pan     = self._QUADRANT_PAN.get(quadrant, 0.5)
        self.trajectory_x = trajectory_x
        self.speed        = speed
        self.phase        = 0.0  # continuous LFO phase

        # Elevation parameters
        self.elevation = float(elevation)
        self.elevation_motion = elevation_motion
        self.elevation_speed = float(elevation_speed)
        self.elevation_range = float(elevation_range)
        self.elevation_phase = 0.0

        # Crossover filter for elevation processing (2nd order Butterworth at 800Hz)
        nyquist = SR * 0.5
        crossover_freq = min(800.0 / nyquist, 0.999)
        self._lp_sos = butter(2, crossover_freq, btype="low", output="sos")
        self._hp_sos = butter(2, crossover_freq, btype="high", output="sos")
        self._lp_zi_L = sosfilt_zi(self._lp_sos) * 0.0
        self._lp_zi_R = sosfilt_zi(self._lp_sos) * 0.0
        self._hp_zi_L = sosfilt_zi(self._hp_sos) * 0.0
        self._hp_zi_R = sosfilt_zi(self._hp_sos) * 0.0

    def _get_elevation_angle(self) -> float:
        """Compute current elevation angle based on motion pattern."""
        half_range = self.elevation_range / 2.0
        if self.elevation_motion == "rise":
            # Sawtooth from -range/2 to +range/2
            cycle = (self.elevation_phase * self.elevation_speed) % 1.0
            return self.elevation + (-half_range + cycle * self.elevation_range)
        elif self.elevation_motion == "fall":
            cycle = (self.elevation_phase * self.elevation_speed) % 1.0
            return self.elevation + (half_range - cycle * self.elevation_range)
        elif self.elevation_motion == "float":
            # Sine wave
            return self.elevation + np.sin(2 * np.pi * self.elevation_speed * self.elevation_phase) * half_range
        elif self.elevation_motion == "breathe":
            # Triangle wave
            cycle = (self.elevation_phase * self.elevation_speed) % 1.0
            tri = 1.0 - abs(2.0 * cycle - 1.0)  # 0→1→0
            return self.elevation + (-half_range + tri * self.elevation_range)
        else:  # static
            return self.elevation

    def next_chunk(self, mono: np.ndarray) -> np.ndarray:
        n = len(mono)
        dt = 1.0 / SR
        t = self.phase + np.arange(n) * dt
        self.phase = t[-1] + dt

        # Pan automation
        if self.trajectory_x == "orbit":
            pan = self.base_pan + np.sin(2 * np.pi * self.speed * t) * 0.32
        elif self.trajectory_x == "pendulum":
            pan = self.base_pan + np.sin(2 * np.pi * self.speed * t) * 0.25
        elif self.trajectory_x == "drift":
            pan = (self.base_pan
                   + np.sin(2 * np.pi * self.speed * t) * 0.12
                   + np.sin(2 * np.pi * self.speed * 1.7 * t) * 0.08)
        elif self.trajectory_x == "spiral":
            depth = 0.05 + 0.33 * (np.sin(2 * np.pi * 0.008 * t) * 0.5 + 0.5)
            pan = self.base_pan + np.sin(2 * np.pi * self.speed * t) * depth
        else:
            pan = np.full(n, self.base_pan)

        pan = np.clip(pan, 0.0, 1.0)

        # Equal-power panning
        angle = pan * (np.pi / 2)
        left  = mono * np.cos(angle)
        right = mono * np.sin(angle)

        # Elevation processing (HRTF-like spectral filtering)
        current_elev = self._get_elevation_angle()
        self.elevation_phase += n * dt

        # Only apply if elevation is non-zero
        if abs(current_elev) > 0.5:
            elev_norm = np.clip(current_elev / 90.0, -1.0, 1.0)
            high_gain = 1.0 + elev_norm * 0.5   # above: boost highs
            low_gain = 1.0 - elev_norm * 0.25   # above: reduce lows

            # Split into low/high bands using crossover
            low_L, self._lp_zi_L = sosfilt(self._lp_sos, left, zi=self._lp_zi_L)
            low_R, self._lp_zi_R = sosfilt(self._lp_sos, right, zi=self._lp_zi_R)
            high_L, self._hp_zi_L = sosfilt(self._hp_sos, left, zi=self._hp_zi_L)
            high_R, self._hp_zi_R = sosfilt(self._hp_sos, right, zi=self._hp_zi_R)

            # Apply elevation-dependent gains and recombine
            left = low_L * low_gain + high_L * high_gain
            right = low_R * low_gain + high_R * high_gain

        return np.stack([left, right], axis=1)


# ── Streaming Chorus ──────────────────────────────────────────────────────────

class StreamingChorus:
    """Per-layer stereo chorus with modulated delay lines."""

    def __init__(self, rate=0.5, depth=0.005, mix=0.0, voices=2):
        self.rate = float(rate)
        self.depth = float(depth)
        self.mix = float(mix)
        self.n_voices = int(voices)
        self.max_delay = int(0.03 * SR) + 1
        self.buffer_size = self.max_delay + 8192
        self.buf_L = np.zeros(self.buffer_size, dtype=np.float32)
        self.buf_R = np.zeros(self.buffer_size, dtype=np.float32)
        self.write_pos = 0
        self.lfo_phases = np.linspace(0, 2 * np.pi, self.n_voices, endpoint=False)
        self.center_delay = int(0.015 * SR)

    def next_chunk(self, stereo: np.ndarray) -> np.ndarray:
        if self.mix < 0.001:
            return stereo
        n = len(stereo)

        # Write chunk into circular buffer
        end_pos = self.write_pos + n
        if end_pos <= self.buffer_size:
            self.buf_L[self.write_pos:end_pos] = stereo[:, 0]
            self.buf_R[self.write_pos:end_pos] = stereo[:, 1]
        else:
            first = self.buffer_size - self.write_pos
            self.buf_L[self.write_pos:] = stereo[:first, 0]
            self.buf_R[self.write_pos:] = stereo[:first, 1]
            self.buf_L[:n - first] = stereo[first:, 0]
            self.buf_R[:n - first] = stereo[first:, 1]

        # Compute wet signal
        wet_L = np.zeros(n, dtype=np.float32)
        wet_R = np.zeros(n, dtype=np.float32)
        depth_samples = self.depth * SR
        lfo_inc = 2 * np.pi * self.rate / SR
        sample_indices = np.arange(n)

        for v in range(self.n_voices):
            # LFO for this voice across all samples
            phases = self.lfo_phases[v] + lfo_inc * sample_indices
            mod = np.sin(phases) * depth_samples
            delay = self.center_delay + mod

            # Read positions (fractional)
            read_pos = (self.write_pos + sample_indices - delay)
            idx0 = np.floor(read_pos).astype(np.int64) % self.buffer_size
            idx1 = (idx0 + 1) % self.buffer_size
            frac = read_pos - np.floor(read_pos)

            wet_L += self.buf_L[idx0] * (1 - frac) + self.buf_L[idx1] * frac
            wet_R += self.buf_R[idx0] * (1 - frac) + self.buf_R[idx1] * frac

            self.lfo_phases[v] = (phases[-1] + lfo_inc) % (2 * np.pi)

        wet_L /= self.n_voices
        wet_R /= self.n_voices

        # Update write position
        self.write_pos = end_pos % self.buffer_size

        # Mix dry + wet
        out = stereo.copy()
        out[:, 0] = stereo[:, 0] * (1 - self.mix) + wet_L * self.mix
        out[:, 1] = stereo[:, 1] * (1 - self.mix) + wet_R * self.mix
        return out


class StreamingLayerFilter:
    """Per-layer biquad filter with optional LFO modulation on cutoff."""

    def __init__(self, filter_type: str, cutoff: float, resonance: float,
                 lfo_rate: float, lfo_depth: float, lfo_shape: str):
        self.filter_type = filter_type
        self.base_cutoff = float(cutoff)
        self.resonance = float(resonance)
        self.lfo_rate = float(lfo_rate)
        self.lfo_depth = float(lfo_depth)
        self.lfo_shape = lfo_shape
        self.lfo_phase = 0.0
        self._last_random = 0.0
        self._sos = None
        self._zi_L = None
        self._zi_R = None
        self._build_filter(self.base_cutoff)

    def _build_filter(self, cutoff: float) -> None:
        nyq = SR * 0.5
        fc = float(np.clip(cutoff, 20.0, nyq * 0.99))
        try:
            if self.filter_type == "lp":
                self._sos = butter(2, fc / nyq, btype="low", output="sos")
            elif self.filter_type == "hp":
                self._sos = butter(2, fc / nyq, btype="high", output="sos")
            elif self.filter_type == "bp":
                lo = np.clip(fc * 0.7, 20, nyq * 0.98)
                hi = np.clip(fc * 1.4, lo + 10, nyq * 0.99)
                self._sos = butter(2, [lo / nyq, hi / nyq], btype="band", output="sos")
            else:
                self._sos = None
                return
        except Exception:
            self._sos = None
            return
        zi = sosfilt_zi(self._sos) * 0.0
        if self._zi_L is None or self._zi_L.shape != zi.shape:
            self._zi_L = zi.copy()
            self._zi_R = zi.copy()

    def _lfo_value(self, n_samples: int) -> float:
        """Return scalar LFO value in range [-1, 1] for this chunk."""
        dt = 1.0 / SR
        phase = self.lfo_phase
        if self.lfo_shape == "sine":
            val = np.sin(2 * np.pi * self.lfo_rate * phase)
        elif self.lfo_shape == "triangle":
            cycle = (self.lfo_rate * phase) % 1.0
            val = 1.0 - abs(2.0 * cycle - 1.0) * 2.0
        elif self.lfo_shape == "square":
            cycle = (self.lfo_rate * phase) % 1.0
            val = 1.0 if cycle < 0.5 else -1.0
        else:
            if np.random.random() < self.lfo_rate * n_samples / SR:
                self._last_random = np.random.uniform(-1, 1)
            val = self._last_random
        self.lfo_phase += n_samples * dt
        return float(val)

    def next_chunk(self, stereo: np.ndarray) -> np.ndarray:
        if self.filter_type == "off" or self._sos is None:
            return stereo
        n = len(stereo)
        if self.lfo_depth > 0.001:
            lfo_val = self._lfo_value(n)
            octaves = lfo_val * self.lfo_depth * 2.0
            modulated_cutoff = self.base_cutoff * (2.0 ** octaves)
            self._build_filter(modulated_cutoff)
        else:
            self._lfo_value(n)
        if self._sos is None:
            return stereo
        filtered_L, self._zi_L = sosfilt(self._sos, stereo[:, 0], zi=self._zi_L)
        filtered_R, self._zi_R = sosfilt(self._sos, stereo[:, 1], zi=self._zi_R)
        return np.stack([filtered_L, filtered_R], axis=1).astype(np.float32)


# ── Streaming Engine ──────────────────────────────────────────────────────────

class StreamingDroneEngine:
    """
    Chunk-based drone engine for real-time preview.

    Usage:
        engine = StreamingDroneEngine(preset)
        while running:
            chunk = engine.next_chunk(2048)  # (2048, 2) stereo float64
            stream.write(chunk)

        # Hot-reload:
        engine.reload(new_preset)  # crossfades to new parameters
    """

    def __init__(self, preset: dict, seed: int = 42):
        self.chunk_size = 2048
        # Seed random state for reproducible preview
        random.seed(seed)
        np.random.seed(seed)
        self._build_from_preset(preset)
        self._crossfade_remaining = 0
        self._old_engine: Optional['StreamingDroneEngine'] = None

    def _build_from_preset(self, preset: dict) -> None:
        self.preset = preset
        self.layers = []
        self.panners = []
        self.choruses = []
        self.filters = []
        self.saturation = float(preset.get("saturation", 0.3))
        self._master = MasterProcessor(preset.get("master", {}), SR)

        for layer_cfg in preset["layers"]:
            if not layer_cfg.get("enabled", True):
                continue
            # Choose layer type: granular, subtractive, or FM
            if layer_cfg.get("type") == "granular":
                samples_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")
                layer = StreamingGranularLayer(layer_cfg, samples_dir, sample_rate=SR)
            elif layer_cfg.get("type") == "subtractive":
                layer = StreamingSubtractiveLayer(layer_cfg)
            else:
                layer = StreamingLayer(layer_cfg)
            panner = StreamingPanner(
                quadrant         = layer_cfg["quadrant"],
                trajectory_x    = layer_cfg["trajectory_x"],
                speed            = layer_cfg["speed"],
                elevation        = float(layer_cfg.get("elevation", 0.0)),
                elevation_motion = layer_cfg.get("elevation_motion", "static"),
                elevation_speed  = float(layer_cfg.get("elevation_speed", 0.1)),
                elevation_range  = float(layer_cfg.get("elevation_range", 60.0)),
            )
            chorus = StreamingChorus(
                rate=float(layer_cfg.get("chorus_rate", 0.5)),
                depth=float(layer_cfg.get("chorus_depth", 0.005)),
                mix=float(layer_cfg.get("chorus_mix", 0.0)),
                voices=int(layer_cfg.get("chorus_voices", 2)),
            )
            layer_filter = StreamingLayerFilter(
                filter_type=layer_cfg.get("filter_type", "off"),
                cutoff=float(layer_cfg.get("filter_cutoff", 2000)),
                resonance=float(layer_cfg.get("filter_resonance", 1.0)),
                lfo_rate=float(layer_cfg.get("filter_lfo_rate", 0.1)),
                lfo_depth=float(layer_cfg.get("filter_lfo_depth", 0.0)),
                lfo_shape=layer_cfg.get("filter_lfo_shape", "sine"),
            )
            self.layers.append(layer)
            self.panners.append(panner)
            self.choruses.append(chorus)
            self.filters.append(layer_filter)

        # Earth engine (simple streaming sine)
        self.earth_cfg = preset.get("earth")
        self.earth_phase = 0.0
        self.earth_wobble_phase = 0.0

        # Air engine (streaming noise)
        self.air_cfg = preset.get("air")
        self._air_kernel = int(0.1 * SR)
        self._air_buffer = np.zeros(self._air_kernel, dtype=np.float32)

        # DC block filter state
        nyquist = SR * 0.5
        self._dc_sos = butter(4, max(18 / nyquist, 0.001), btype="high", output="sos")
        self._dc_zi_L = sosfilt_zi(self._dc_sos) * 0.0
        self._dc_zi_R = sosfilt_zi(self._dc_sos) * 0.0

    def next_chunk(self, n_samples: Optional[int] = None) -> np.ndarray:
        """Generate the next chunk of stereo audio (n_samples, 2)."""
        n = n_samples or self.chunk_size
        stereo = np.zeros((n, 2), dtype=np.float32)

        # Layers
        for layer, panner, chorus, layer_filter in zip(self.layers, self.panners, self.choruses, self.filters):
            mono = layer.next_chunk(n)
            panned = panner.next_chunk(mono)
            chorused = chorus.next_chunk(panned)
            stereo += layer_filter.next_chunk(chorused)

        # Earth
        if self.earth_cfg and self.earth_cfg.get("enabled", True):
            stereo += self._earth_chunk(n)

        # Air
        if self.air_cfg and self.air_cfg.get("enabled", True):
            stereo += self._air_chunk(n)

        # DC block
        stereo[:, 0], self._dc_zi_L = sosfilt(self._dc_sos, stereo[:, 0], zi=self._dc_zi_L)
        stereo[:, 1], self._dc_zi_R = sosfilt(self._dc_sos, stereo[:, 1], zi=self._dc_zi_R)

        # Soft saturation (warm analog-style tanh waveshaping)
        if self.saturation > 0.01:
            drive = 1.0 + self.saturation * 3.0
            norm = np.tanh(drive)
            stereo = np.tanh(stereo * drive) / norm

        # Normalize chunk (soft limiter to prevent clipping)
        peak = np.max(np.abs(stereo))
        if peak > 0.92:
            stereo = stereo * (0.92 / peak)

        stereo = self._master.process(stereo)

        # Handle crossfade from hot-reload
        if self._crossfade_remaining > 0 and self._old_engine is not None:
            old_chunk = self._old_engine.next_chunk(n)
            fade_len = min(n, self._crossfade_remaining)
            fade_out = np.linspace(1, 0, fade_len)[:, None]
            fade_in  = np.linspace(0, 1, fade_len)[:, None]
            stereo[:fade_len] = old_chunk[:fade_len] * fade_out + stereo[:fade_len] * fade_in
            if fade_len < n:
                pass  # rest is fully new engine
            self._crossfade_remaining -= fade_len
            if self._crossfade_remaining <= 0:
                self._old_engine = None

        return stereo

    def reload(self, new_preset: dict, crossfade_secs: float = 3.0) -> None:
        """
        Hot-reload: swap to a new preset with a smooth crossfade.
        The old engine continues generating during the crossfade.
        """
        # Clone current state as the "old" engine for crossfade
        self._old_engine = _ShallowCopy(self)
        self._crossfade_remaining = int(crossfade_secs * SR)

        # Rebuild with new preset
        self._build_from_preset(new_preset)

    def _earth_chunk(self, n: int) -> np.ndarray:
        cfg = self.earth_cfg
        dt = 1.0 / SR
        freq = float(cfg.get("tectonic_frequency", 18))
        pressure = float(cfg.get("pressure", 0.4))
        movement = float(cfg.get("movement", 0.02))

        t = np.arange(n) * dt

        # Wobble
        wobble_inc = 2 * np.pi * movement * t
        wobble_phases = self.earth_wobble_phase + np.cumsum(wobble_inc * dt * SR)
        # Simpler: just use time accumulator
        wobble_t = self.earth_wobble_phase + np.arange(n) * dt
        wobble = np.sin(2 * np.pi * movement * wobble_t) * 0.5
        self.earth_wobble_phase = wobble_t[-1] + dt

        # Earth tone
        earth_t = self.earth_phase + np.arange(n) * dt
        earth = np.sin(2 * np.pi * (freq + wobble) * earth_t)
        pressure_wave = np.sin(2 * np.pi * freq * 0.5 * earth_t) * 0.6
        self.earth_phase = earth_t[-1] + dt

        signal = (earth * 0.7 + pressure_wave * 0.3) * pressure

        # Pan center with drift
        stereo = np.stack([signal * 0.5, signal * 0.5], axis=1)
        return stereo

    def _air_chunk(self, n: int) -> np.ndarray:
        cfg = self.air_cfg
        intensity  = float(cfg.get("intensity", 0.12))
        turbulence = float(cfg.get("turbulence", 0.04))

        # Smoothed noise
        noise = np.random.randn(n) * turbulence
        # Simple exponential smoothing instead of full convolution
        alpha = 2.0 / (self._air_kernel + 1)
        smoothed = np.zeros(n, dtype=np.float32)
        state = self._air_buffer[-1] if len(self._air_buffer) > 0 else 0.0
        for i in range(n):
            state = alpha * noise[i] + (1 - alpha) * state
            smoothed[i] = state

        signal = smoothed * intensity
        stereo = np.stack([signal * 0.5, signal * 0.5], axis=1)
        return stereo


class _ShallowCopy:
    """
    Wraps an engine's current state for crossfade.
    Captures the layers/panners so the old sound continues briefly.
    """

    def __init__(self, engine: StreamingDroneEngine):
        self.layers  = engine.layers
        self.panners = engine.panners
        self.choruses = engine.choruses
        self.filters = engine.filters
        self.earth_cfg = engine.earth_cfg
        self.air_cfg   = engine.air_cfg
        self.earth_phase = engine.earth_phase
        self.earth_wobble_phase = engine.earth_wobble_phase
        self._air_kernel = engine._air_kernel
        self._air_buffer = engine._air_buffer.copy()
        self._dc_sos  = engine._dc_sos
        self._dc_zi_L = engine._dc_zi_L.copy()
        self._dc_zi_R = engine._dc_zi_R.copy()
        self.saturation = engine.saturation
        self._master = engine._master.copy_state()
        self._crossfade_remaining = 0
        self._old_engine = None

    def next_chunk(self, n: int) -> np.ndarray:
        stereo = np.zeros((n, 2), dtype=np.float32)
        for layer, panner, chorus, layer_filter in zip(self.layers, self.panners, self.choruses, self.filters):
            mono = layer.next_chunk(n)
            panned = panner.next_chunk(mono)
            chorused = chorus.next_chunk(panned)
            stereo += layer_filter.next_chunk(chorused)

        stereo[:, 0], self._dc_zi_L = sosfilt(self._dc_sos, stereo[:, 0], zi=self._dc_zi_L)
        stereo[:, 1], self._dc_zi_R = sosfilt(self._dc_sos, stereo[:, 1], zi=self._dc_zi_R)

        # Soft saturation
        if self.saturation > 0.01:
            drive = 1.0 + self.saturation * 3.0
            norm = np.tanh(drive)
            stereo = np.tanh(stereo * drive) / norm

        peak = np.max(np.abs(stereo))
        if peak > 0.92:
            stereo = stereo * (0.92 / peak)

        stereo = self._master.process(stereo)

        return stereo

