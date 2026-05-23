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

import json
import os
import random
import urllib.request
from typing import Optional, Callable

import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi, lfilter

# Formant frequencies (Hz) and bandwidths (Hz) for the five primary vowels
VOWEL_FORMANTS: dict = {
    'a': [(800, 120), (1200, 180), (2500, 280)],
    'e': [(400,  80), (2000, 200), (2800, 300)],
    'i': [(270,  60), (2300, 200), (3000, 300)],
    'o': [(570,  80), ( 850, 120), (2500, 280)],
    'u': [(380,  70), ( 950, 100), (2200, 250)],
}

from . import config
from .granular_layer import StreamingGranularLayer
from .master_processing import MasterProcessor


def _ensure_freesound_sample(source_file: str, samples_dir: str) -> str:
    """Ensure a freesound_cache/ file exists, re-downloading from Freesound API if needed.
    Returns source_file if available (re-downloaded if necessary), or 'singing_bowl.ogg' as fallback."""
    import re as _re

    filepath = os.path.join(samples_dir, source_file)
    if os.path.exists(filepath):
        return source_file

    if not source_file.startswith("freesound_cache/"):
        return "singing_bowl.ogg"

    m = _re.match(r'^freesound_cache/(\d+)\.(ogg|mp3)$', source_file)
    if not m:
        return "singing_bowl.ogg"

    sound_id = m.group(1)
    cache_dir = os.path.join(samples_dir, "freesound_cache")
    preview_url = None

    # Check local cache manifest first
    manifest_path = os.path.join(cache_dir, "manifest.json")
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path) as f:
                for entry in json.load(f):
                    if str(entry.get("id")) == sound_id:
                        preview_url = entry.get("preview_url")
                        break
        except Exception:
            pass

    # Fall back to Freesound API lookup
    if not preview_url:
        api_key = os.environ.get("FREESOUND_API_KEY", "zwjXCAeWopixCMievVQ5q1FLmyh1DBvMf4HJuqNE")
        try:
            url = f"https://freesound.org/apiv2/sounds/{sound_id}/?token={api_key}&fields=previews"
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
            preview_url = (data.get("previews") or {}).get("preview-hq-ogg") or \
                          (data.get("previews") or {}).get("preview-hq-mp3")
        except Exception:
            return "singing_bowl.ogg"

    if not preview_url:
        return "singing_bowl.ogg"

    os.makedirs(cache_dir, exist_ok=True)
    ext = "ogg" if preview_url.endswith(".ogg") else "mp3"
    dest = os.path.join(cache_dir, f"{sound_id}.{ext}")
    try:
        urllib.request.urlretrieve(preview_url, dest)
        return f"freesound_cache/{sound_id}.{ext}"
    except Exception:
        return "singing_bowl.ogg"

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
                 elevation_speed: float = 0.1, elevation_range: float = 60.0,
                 pan: float = 0.0, width: float = 1.0):
        # Pan: -1.0 (L) to +1.0 (R); 0 = use quadrant. Width: 0=mono, 1=normal, 2=wide.
        if pan != 0.0:
            self.base_pan = (pan + 1.0) / 2.0
        else:
            self.base_pan = self._QUADRANT_PAN.get(quadrant, 0.5)
        self.width        = float(width)
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

    def _apply_width(self, stereo: np.ndarray) -> np.ndarray:
        """Mid/side width processing. width=0 mono, width=1 normal, width=2 extra-wide."""
        if abs(self.width - 1.0) < 0.01:
            return stereo
        mid  = (stereo[:, 0] + stereo[:, 1]) * 0.5
        side = (stereo[:, 0] - stereo[:, 1]) * 0.5
        w = self.width
        out = np.stack([mid + side * w, mid - side * w], axis=1)
        return out

    def process(self, mono: np.ndarray) -> np.ndarray:
        """Pan + width in one call."""
        return self._apply_width(self.next_chunk(mono))


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
    """Per-layer filter: biquad (LP/HP/BP) with LFO, feedforward comb, or vowel formant."""

    def __init__(self, filter_type: str, cutoff: float, resonance: float,
                 lfo_rate: float, lfo_depth: float, lfo_shape: str, vowel: str = 'a'):
        self.filter_type = filter_type
        self.base_cutoff = float(cutoff)
        self.resonance = float(resonance)
        self.lfo_rate = float(lfo_rate)
        self.lfo_depth = float(lfo_depth)
        self.lfo_shape = lfo_shape
        self.vowel = vowel
        self.lfo_phase = 0.0
        self._last_random = 0.0
        self._sos = None
        self._zi_L = None
        self._zi_R = None
        # Comb filter state
        self._comb_buf_L: np.ndarray = np.zeros(1, dtype=np.float32)
        self._comb_buf_R: np.ndarray = np.zeros(1, dtype=np.float32)
        self._comb_delay: int = 1
        # Formant filter state
        self._formant_sos_list: list = []
        self._formant_zi_list: list = []

        if filter_type == 'comb':
            self._init_comb(self.base_cutoff)
        elif filter_type == 'formant':
            self._init_formant(self.vowel)
        else:
            self._build_filter(self.base_cutoff)

    # ── Comb filter ──────────────────────────────────────────────────────────

    def _init_comb(self, cutoff: float) -> None:
        """Feedforward comb: y[n] = x[n] + g * x[n - D], D = SR / cutoff."""
        freq = float(np.clip(cutoff, 20.0, SR * 0.49))
        self._comb_delay = max(1, int(round(SR / freq)))
        self._comb_buf_L = np.zeros(self._comb_delay, dtype=np.float32)
        self._comb_buf_R = np.zeros(self._comb_delay, dtype=np.float32)

    def _next_chunk_comb(self, stereo: np.ndarray) -> np.ndarray:
        n = len(stereo)
        D = self._comb_delay
        g = float(np.clip(self.resonance / 8.0 * 0.97, 0.0, 0.97))
        # Extend input with the tail of the previous chunk to get delayed signal
        ext_L = np.concatenate([self._comb_buf_L, stereo[:, 0]])
        ext_R = np.concatenate([self._comb_buf_R, stereo[:, 1]])
        out_L = (stereo[:, 0] + g * ext_L[:n]).astype(np.float32)
        out_R = (stereo[:, 1] + g * ext_R[:n]).astype(np.float32)
        # Retain last D input samples for next chunk
        self._comb_buf_L = ext_L[-D:].copy()
        self._comb_buf_R = ext_R[-D:].copy()
        return np.stack([out_L, out_R], axis=1)

    # ── Formant filter ───────────────────────────────────────────────────────

    def _init_formant(self, vowel: str) -> None:
        """Three parallel bandpass filters at vowel formant frequencies."""
        formants = VOWEL_FORMANTS.get(vowel, VOWEL_FORMANTS['a'])
        nyq = SR * 0.5
        self._formant_sos_list = []
        self._formant_zi_list = []
        for f0, bw in formants:
            lo = max(f0 - bw / 2.0, 20.0) / nyq
            hi = min(f0 + bw / 2.0, nyq * 0.99) / nyq
            lo = min(lo, hi - 0.01)
            try:
                sos = butter(2, [lo, hi], btype='band', output='sos')
                zi = sosfilt_zi(sos) * 0.0
                self._formant_sos_list.append(sos)
                self._formant_zi_list.append([zi.copy(), zi.copy()])
            except Exception:
                pass

    def _next_chunk_formant(self, stereo: np.ndarray) -> np.ndarray:
        if not self._formant_sos_list:
            return stereo
        n = len(stereo)
        wet = float(np.clip(self.resonance / 8.0, 0.0, 1.0))
        if wet < 0.001:
            return stereo
        wet_L = np.zeros(n, dtype=np.float32)
        wet_R = np.zeros(n, dtype=np.float32)
        for i, sos in enumerate(self._formant_sos_list):
            zi_L, zi_R = self._formant_zi_list[i]
            filt_L, new_zi_L = sosfilt(sos, stereo[:, 0], zi=zi_L)
            filt_R, new_zi_R = sosfilt(sos, stereo[:, 1], zi=zi_R)
            wet_L += filt_L.astype(np.float32)
            wet_R += filt_R.astype(np.float32)
            self._formant_zi_list[i] = [new_zi_L, new_zi_R]
        k = len(self._formant_sos_list)
        wet_L /= k
        wet_R /= k
        out = stereo.copy()
        out[:, 0] = stereo[:, 0] * (1.0 - wet) + wet_L * wet
        out[:, 1] = stereo[:, 1] * (1.0 - wet) + wet_R * wet
        return out.astype(np.float32)

    # ── Biquad helper ────────────────────────────────────────────────────────

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
        if self.filter_type == "comb":
            return self._next_chunk_comb(stereo)
        if self.filter_type == "formant":
            return self._next_chunk_formant(stereo)
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


# ── Flanger ───────────────────────────────────────────────────────────────────

class StreamingFlanger:
    """Global stereo flanger: short LFO-modulated delay line on the full mix."""

    def __init__(self, rate: float = 0.25, depth: float = 0.5,
                 feedback: float = 0.4, wet: float = 0.0):
        self.rate = float(rate)         # LFO Hz (0.01–2.0)
        self.depth = float(depth)       # modulation depth (0–1)
        self.feedback = float(feedback) # feedback amount (0–0.95)
        self.wet = float(wet)           # dry/wet mix (0–1)
        self.lfo_phase = 0.0

        # Delay range: 0.5 ms base, up to 10 ms of LFO modulation
        self._min_delay = max(1, int(0.0005 * SR))
        self._max_mod   = int(0.010 * SR)
        buf_size = self._min_delay + self._max_mod + 4096
        self._buf_L  = np.zeros(buf_size, dtype=np.float32)
        self._buf_R  = np.zeros(buf_size, dtype=np.float32)
        self._write  = 0
        self._buf_sz = buf_size
        self._fb_L   = 0.0  # feedback state from last output sample
        self._fb_R   = 0.0

    def next_chunk(self, stereo: np.ndarray) -> np.ndarray:
        if self.wet < 0.001:
            return stereo
        n = len(stereo)
        fb = float(np.clip(self.feedback, 0.0, 0.95))

        # Write dry + single-sample feedback into the delay buffer
        write_L = stereo[:, 0].copy()
        write_R = stereo[:, 1].copy()
        write_L[0] += fb * self._fb_L
        write_R[0] += fb * self._fb_R

        end_pos = self._write + n
        if end_pos <= self._buf_sz:
            self._buf_L[self._write:end_pos] = write_L
            self._buf_R[self._write:end_pos] = write_R
        else:
            first = self._buf_sz - self._write
            self._buf_L[self._write:] = write_L[:first]
            self._buf_R[self._write:] = write_R[:first]
            self._buf_L[:n - first]   = write_L[first:]
            self._buf_R[:n - first]   = write_R[first:]

        # LFO sweep
        lfo_inc  = 2.0 * np.pi * self.rate / SR
        sample_t = np.arange(n, dtype=np.float64)
        phases   = self.lfo_phase + lfo_inc * sample_t
        lfo      = np.sin(phases)

        # Modulated delay in samples
        center  = self._min_delay + self._max_mod * 0.5
        delay_s = center + lfo * (self._max_mod * 0.5 * self.depth)

        # Linear-interpolated read from circular buffer
        read_pos = (self._write + sample_t - delay_s) % self._buf_sz
        idx0 = np.floor(read_pos).astype(np.int64) % self._buf_sz
        idx1 = (idx0 + 1) % self._buf_sz
        frac = (read_pos - np.floor(read_pos)).astype(np.float32)

        wet_L = (self._buf_L[idx0] * (1.0 - frac) + self._buf_L[idx1] * frac).astype(np.float32)
        wet_R = (self._buf_R[idx0] * (1.0 - frac) + self._buf_R[idx1] * frac).astype(np.float32)

        self._fb_L   = float(wet_L[-1])
        self._fb_R   = float(wet_R[-1])
        self.lfo_phase = float((phases[-1] + lfo_inc) % (2.0 * np.pi))
        self._write  = end_pos % self._buf_sz

        out = stereo.copy()
        out[:, 0] = stereo[:, 0] * (1.0 - self.wet) + wet_L * self.wet
        out[:, 1] = stereo[:, 1] * (1.0 - self.wet) + wet_R * self.wet
        return out.astype(np.float32)






# ── FDN Reverb ────────────────────────────────────────────────────────────────

class StreamingFDNReverb:
    """
    8-line Feedback Delay Network reverb for real-time streaming.

    Features:
      - Block-based processing (all delay lines > chunk size = vectorised)
      - Hadamard H8 feedback matrix for dense diffusion
      - Per-line 1-pole damping lowpass
      - Pre-delay buffer (0–150 ms, inserted before FDN input)
      - Per-line LFO modulation (slow, breaks metallic resonances)
      - Stereo decorrelation: even lines → L, odd lines → R
    """

    # Delay line lengths (samples at 22050 Hz).  ALL values exceed 2048
    # (one chunk) so the block-based feedback approach is exact.
    _SPACES: dict[str, list[int]] = {
        "cathedral": [2053, 2113, 2203, 2311, 2399, 2503, 2617, 2719],
        "hall":      [2053, 2081, 2131, 2179, 2243, 2311, 2383, 2467],
        "cave":      [2311, 2411, 2543, 2677, 2789, 2903, 3019, 3137],
        "plate":     [2053, 2063, 2069, 2081, 2083, 2087, 2089, 2099],
        "infinite":  [2713, 2879, 3049, 3221, 3413, 3581, 3779, 3943],
    }
    # Per-space damping coefficients (higher = duller reverb tail)
    _DAMP: dict[str, float] = {
        "cathedral": 0.28, "hall": 0.35, "cave": 0.18,
        "plate": 0.50,     "infinite": 0.10,
    }

    # Normalised 8×8 Hadamard matrix
    _H8 = np.array([
        [ 1, 1, 1, 1, 1, 1, 1, 1],
        [ 1,-1, 1,-1, 1,-1, 1,-1],
        [ 1, 1,-1,-1, 1, 1,-1,-1],
        [ 1,-1,-1, 1, 1,-1,-1, 1],
        [ 1, 1, 1, 1,-1,-1,-1,-1],
        [ 1,-1, 1,-1,-1, 1,-1, 1],
        [ 1, 1,-1,-1,-1,-1, 1, 1],
        [ 1,-1,-1, 1,-1, 1, 1,-1],
    ], dtype=np.float64) / np.sqrt(8)

    _N_LINES       = 8
    _MAX_PRE_DELAY = int(0.150 * SR)   # 3308 samples @ 22050 Hz
    _LFO_DEPTH_MAX = 5.0               # ±5 samples maximum modulation

    def __init__(self, reverb_cfg: dict):
        self.enabled = bool(reverb_cfg.get("enabled", False))
        self.mix     = float(reverb_cfg.get("mix", 0.3))

        # Map decay_trim (0.1–1.0) → feedback gain (0.60–0.96)
        decay_trim  = float(reverb_cfg.get("decay_trim", 1.0))
        self.decay  = 0.60 + decay_trim * 0.36

        # Pre-delay
        self.pre_delay_ms      = float(reverb_cfg.get("pre_delay_ms", 0.0))
        self._pre_delay_samps  = min(
            int(self.pre_delay_ms * SR / 1000.0), self._MAX_PRE_DELAY
        )

        # Modulation depth (0–1 → 0–5 samples swing)
        self.mod_depth = float(reverb_cfg.get("modulation_depth", 0.0))

        # Choose space
        space = reverb_cfg.get("space", "cathedral")
        self.delays = np.array(
            self._SPACES.get(space, self._SPACES["cathedral"]), dtype=np.int32
        )
        self.max_d  = int(self.delays.max()) + 1

        # Precomputed Hadamard × decay (applied every chunk)
        self._H8d = self._H8 * self.decay

        # Damping coefficient and filter state (1-pole lowpass, per line)
        d = self._DAMP.get(space, 0.30)
        self._damp_b  = np.array([(1.0 - d)], dtype=np.float64)
        self._damp_a  = np.array([1.0, -d],   dtype=np.float64)
        self._damp_zi = np.zeros(self._N_LINES, dtype=np.float64)   # shape (8,)

        # Circular delay-line buffers  (N_LINES × max_d)
        self.buf       = np.zeros((self._N_LINES, self.max_d), dtype=np.float64)
        self.write_ptr = 0

        # Pre-delay circular buffer
        self._pre_buf = np.zeros(self._MAX_PRE_DELAY + 4096, dtype=np.float64)
        self._pre_ptr = 0

        # Per-line LFO state
        rng = np.random.default_rng(seed=42)
        self._lfo_phases = rng.uniform(0.0, 2 * np.pi, self._N_LINES)
        self._lfo_rates  = rng.uniform(0.1, 0.5, self._N_LINES)   # Hz

    # ------------------------------------------------------------------

    def copy_state(self) -> "StreamingFDNReverb":
        """Deep-copy mutable state for crossfade old_engine."""
        import copy
        clone = copy.copy(self)
        clone.buf        = self.buf.copy()
        clone._damp_zi   = self._damp_zi.copy()
        clone._pre_buf   = self._pre_buf.copy()
        clone._lfo_phases= self._lfo_phases.copy()
        clone._lfo_rates = self._lfo_rates.copy()
        return clone

    # ------------------------------------------------------------------

    def next_chunk(self, stereo: np.ndarray) -> np.ndarray:
        """Apply FDN reverb to stereo chunk (N, 2). Returns same shape."""
        if not self.enabled or self.mix < 0.001:
            return stereo

        n = len(stereo)
        # Mono sum for reverb input
        mono = ((stereo[:, 0] + stereo[:, 1]) * 0.5).astype(np.float64)

        # ── Pre-delay ────────────────────────────────────────────────────
        pd = self._pre_delay_samps
        if pd > 0:
            L   = len(self._pre_buf)
            ptr = self._pre_ptr
            # Read FIRST (before writing) so short pd values are causal
            rs = (ptr - pd) % L
            if rs + n <= L:
                fdn_in = self._pre_buf[rs:rs+n].copy()
            else:
                t2 = L - rs
                fdn_in = np.concatenate([self._pre_buf[rs:], self._pre_buf[:n-t2]])
            # Then write current chunk into the delay buffer
            end = ptr + n
            if end <= L:
                self._pre_buf[ptr:end] = mono
            else:
                tail = L - ptr
                self._pre_buf[ptr:]    = mono[:tail]
                self._pre_buf[:n-tail] = mono[tail:]
            self._pre_ptr = (ptr + n) % L
        else:
            fdn_in = mono

        # ── LFO: advance phases, compute per-line delay offsets (per chunk) ─
        dt = n / SR
        self._lfo_phases += 2.0 * np.pi * self._lfo_rates * dt
        lfo_off = (np.sin(self._lfo_phases) * self._lfo_depth_max
                   * self.mod_depth).astype(np.int32)

        # ── Read from all 8 delay lines (history only, no within-chunk fb) ─
        v = np.empty((self._N_LINES, n), dtype=np.float64)
        for j in range(self._N_LINES):
            d_j = int(self.delays[j]) + int(lfo_off[j])
            d_j = max(n + 1, min(d_j, self.max_d - 1))
            rs  = (self.write_ptr - d_j) % self.max_d
            if rs + n <= self.max_d:
                v[j] = self.buf[j, rs:rs+n]
            else:
                t2 = self.max_d - rs
                v[j, :t2]  = self.buf[j, rs:]
                v[j, t2:]  = self.buf[j, :n-t2]

        # ── Hadamard mix + input injection ───────────────────────────────
        u = self._H8d @ v                          # (8, n) vectorised
        u += fdn_in[np.newaxis, :] * 0.125         # spread mono input evenly

        # ── Per-line 1-pole damping lowpass ──────────────────────────────
        for j in range(self._N_LINES):
            u_j, zi_out = lfilter(
                self._damp_b, self._damp_a, u[j],
                zi=self._damp_zi[j:j+1]   # shape (1,) — correct for lfilter zi
            )
            u[j] = u_j
            self._damp_zi[j] = zi_out[0]

        # ── Write feedback back to delay lines ───────────────────────────
        wp = self.write_ptr
        if wp + n <= self.max_d:
            self.buf[:, wp:wp+n] = u
        else:
            tail = self.max_d - wp
            self.buf[:, wp:]     = u[:, :tail]
            self.buf[:, :n-tail] = u[:, tail:]
        self.write_ptr = (wp + n) % self.max_d

        # ── Stereo output: even lines → L, odd lines → R ─────────────────
        scale = 0.25
        wet_L = (v[0] + v[2] + v[4] + v[6]) * scale
        wet_R = (v[1] + v[3] + v[5] + v[7]) * scale
        wet   = np.column_stack([wet_L, wet_R]).astype(np.float32)

        return (stereo * (1.0 - self.mix) + wet * self.mix).astype(np.float32)

    @property
    def _lfo_depth_max(self) -> float:
        return self._LFO_DEPTH_MAX


class LayerDistortion:
    """Per-layer waveshaper distortion (soft-clip tanh or hard-clip)."""

    def __init__(self, drive: float = 0.0, dist_type: str = "soft"):
        self.drive = float(drive)
        self.dist_type = dist_type

    def process(self, stereo: np.ndarray) -> np.ndarray:
        if self.drive < 0.01:
            return stereo
        d = 1.0 + self.drive * 4.0
        if self.dist_type == "hard":
            return np.clip(stereo * d, -1.0, 1.0) / d
        else:  # soft (tanh)
            return np.tanh(stereo * d) / np.tanh(d)


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
        self._crossfade_total = 0
        self._old_engine: Optional['StreamingDroneEngine'] = None
        self._pending_reload: Optional[tuple] = None  # (new_preset, crossfade_secs)

    def _build_from_preset(self, preset: dict) -> None:
        self.preset = preset
        self.layers = []
        self.panners = []
        self.choruses = []
        self.filters = []
        self.distortions = []
        self.saturation = float(preset.get("saturation", 0.3))
        self._master = MasterProcessor(preset.get("master", {}), SR)

        for layer_cfg in preset["layers"]:
            if layer_cfg.get("muted", False):
                continue
            # Choose layer type: granular, subtractive, or FM
            if layer_cfg.get("type") == "granular":
                samples_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")
                resolved_cfg = dict(layer_cfg)
                resolved_cfg["source"] = _ensure_freesound_sample(
                    layer_cfg.get("source", "singing_bowl.ogg"), samples_dir
                )
                layer = StreamingGranularLayer(resolved_cfg, samples_dir, sample_rate=SR)
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
                pan              = float(layer_cfg.get("pan", 0.0)),
                width            = float(layer_cfg.get("width", 1.0)),
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
                vowel=layer_cfg.get("filter_vowel", "a"),
            )
            self.layers.append(layer)
            self.panners.append(panner)
            self.choruses.append(chorus)
            self.filters.append(layer_filter)
            self.distortions.append(LayerDistortion(
                drive=float(layer_cfg.get("distortion_drive", 0.0)),
                dist_type=layer_cfg.get("distortion_type", "soft"),
            ))

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

        # Global flanger
        flanger_cfg = preset.get("flanger") or {}
        self._flanger = StreamingFlanger(
            rate=float(flanger_cfg.get("rate", 0.25)),
            depth=float(flanger_cfg.get("depth", 0.5)),
            feedback=float(flanger_cfg.get("feedback", 0.4)),
            wet=float(flanger_cfg.get("wet", 0.0)),
        )

        # Global FDN reverb
        self._reverb = StreamingFDNReverb(preset.get("reverb") or {})

    def next_chunk(self, n_samples: Optional[int] = None) -> np.ndarray:
        """Generate the next chunk of stereo audio (n_samples, 2)."""
        n = n_samples or self.chunk_size

        # Apply any pending reload atomically at a chunk boundary.
        # This avoids the race condition where _build_from_preset() mutates
        # self.layers on the event-loop thread while next_chunk() reads them
        # in the thread-pool executor.
        if self._pending_reload is not None:
            new_preset, crossfade_secs = self._pending_reload
            self._pending_reload = None
            self._old_engine = _ShallowCopy(self)
            self._crossfade_total = int(crossfade_secs * SR)
            self._crossfade_remaining = self._crossfade_total
            self._build_from_preset(new_preset)

        stereo = np.zeros((n, 2), dtype=np.float32)

        # Layers
        for layer, panner, chorus, layer_filter, distortion in zip(self.layers, self.panners, self.choruses, self.filters, self.distortions):
            mono = layer.next_chunk(n)
            panned = panner.process(mono)  # pan + width
            chorused = chorus.next_chunk(panned)
            filtered = layer_filter.next_chunk(chorused)
            stereo += distortion.process(filtered)

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

        # FDN reverb
        stereo = self._reverb.next_chunk(stereo)

        # Normalize chunk (soft limiter to prevent clipping)
        peak = np.max(np.abs(stereo))
        if peak > 0.92:
            stereo = stereo * (0.92 / peak)

        stereo = self._master.process(stereo)

        # Handle crossfade from hot-reload
        if self._crossfade_remaining > 0 and self._old_engine is not None:
            old_chunk = self._old_engine.next_chunk(n)
            fade_len = min(n, self._crossfade_remaining)
            # Use GLOBAL position in crossfade so fade continues across chunk boundaries
            pos_start = self._crossfade_total - self._crossfade_remaining
            pos_end   = pos_start + fade_len
            global_t  = np.linspace(pos_start / self._crossfade_total,
                                     pos_end   / self._crossfade_total,
                                     fade_len, endpoint=False)[:, None]
            fade_in   = global_t
            fade_out  = 1.0 - fade_in
            stereo[:fade_len] = old_chunk[:fade_len] * fade_out + stereo[:fade_len] * fade_in
            self._crossfade_remaining -= fade_len
            if self._crossfade_remaining <= 0:
                self._old_engine = None

        # Global flanger (applied after crossfade so it acts on the final mix)
        stereo = self._flanger.next_chunk(stereo)

        return stereo

    def reload(self, new_preset: dict, crossfade_secs: float = 3.0) -> None:
        """
        Queue a hot-reload to the new preset with a smooth crossfade.
        Applied atomically at the start of the next chunk (avoids race condition
        between _build_from_preset on the event loop and next_chunk in a thread).
        If called multiple times before the next chunk fires, only the latest wins.
        """
        self._pending_reload = (new_preset, crossfade_secs)

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
        self.distortions = engine.distortions
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
        self._reverb  = engine._reverb.copy_state()
        self._crossfade_remaining = 0
        self._crossfade_total = 0
        self._old_engine = None

    def next_chunk(self, n: int) -> np.ndarray:
        stereo = np.zeros((n, 2), dtype=np.float32)
        for layer, panner, chorus, layer_filter, distortion in zip(self.layers, self.panners, self.choruses, self.filters, self.distortions):
            mono = layer.next_chunk(n)
            panned = panner.next_chunk(mono)
            chorused = chorus.next_chunk(panned)
            filtered = layer_filter.next_chunk(chorused)
            stereo += distortion.process(filtered)

        stereo[:, 0], self._dc_zi_L = sosfilt(self._dc_sos, stereo[:, 0], zi=self._dc_zi_L)
        stereo[:, 1], self._dc_zi_R = sosfilt(self._dc_sos, stereo[:, 1], zi=self._dc_zi_R)

        # Soft saturation
        if self.saturation > 0.01:
            drive = 1.0 + self.saturation * 3.0
            norm = np.tanh(drive)
            stereo = np.tanh(stereo * drive) / norm

        # FDN reverb
        stereo = self._reverb.next_chunk(stereo)

        peak = np.max(np.abs(stereo))
        if peak > 0.92:
            stereo = stereo * (0.92 / peak)

        stereo = self._master.process(stereo)

        return stereo

