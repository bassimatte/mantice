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
from .automation import parse_layer_automation, parse_global_automation


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


# ── R3: Oversampling Utilities ───────────────────────────────────────────────

def _oversample_waveshaper(audio: np.ndarray, waveshaper_fn, factor: int = 4) -> np.ndarray:
    """
    Apply waveshaper with oversampling to reduce aliasing.
    
    R3: Implements anti-aliasing for nonlinear waveshapers (tanh, clip, etc).
    Process: upsample → waveshape → downsample (with anti-aliasing filters).
    
    Args:
        audio: Input audio (mono or stereo)
        waveshaper_fn: Function that applies waveshaping (takes and returns same shape)
        factor: Oversampling factor (2, 4, or 8). Higher = less aliasing, more CPU.
    
    Returns:
        Processed audio with same shape as input
    """
    from scipy.signal import resample_poly
    
    is_mono = (audio.ndim == 1)
    stereo = np.column_stack([audio, audio]) if is_mono else audio
    
    # Upsample with anti-aliasing filter
    upsampled_L = resample_poly(stereo[:, 0], factor, 1)
    upsampled_R = resample_poly(stereo[:, 1], factor, 1)
    upsampled = np.column_stack([upsampled_L, upsampled_R])
    
    # Apply waveshaper at higher sample rate
    shaped = waveshaper_fn(upsampled)
    
    # Downsample with anti-aliasing filter
    downsampled_L = resample_poly(shaped[:, 0], 1, factor)
    downsampled_R = resample_poly(shaped[:, 1], 1, factor)
    
    # Match original length (resampling may add/remove 1-2 samples)
    target_len = len(audio)
    downsampled_L = downsampled_L[:target_len]
    downsampled_R = downsampled_R[:target_len]
    
    # Pad if needed (rare edge case)
    if len(downsampled_L) < target_len:
        pad_len = target_len - len(downsampled_L)
        downsampled_L = np.concatenate([downsampled_L, np.zeros(pad_len)])
        downsampled_R = np.concatenate([downsampled_R, np.zeros(pad_len)])
    
    result = np.column_stack([downsampled_L, downsampled_R])
    return result[:, 0] if is_mono else result


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

    def __init__(self, cfg: dict, sample_rate: int = None):
        self.SR = sample_rate or SR  # Use passed SR or fallback to module default
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
        # Phases for voices that share the same frequency ratio are distributed
        # within a 90° arc (one quadrant of the unit circle). This guarantees:
        #   (1) No two same-ratio voices are 180° apart → no mono cancellation.
        #   (2) Phases differ → genuine L≠R stereo from the voice spread angles.
        # A random group-start offset makes each session sound different.
        _ratio_count: dict = {}
        for r in ratios:
            _ratio_count[r] = _ratio_count.get(r, 0) + 1
        _ratio_phase_start: dict = {r: random.uniform(0, 2 * np.pi) for r in _ratio_count}
        _ratio_index: dict = {r: 0 for r in _ratio_count}
        carrier_phases_arr = np.zeros(n_voices, dtype=np.float32)
        for i, r in enumerate(ratios):
            n_grp = _ratio_count[r]
            idx   = _ratio_index[r]
            # Spread phases within [0, π/2] — no pair ever reaches the 180° danger zone
            phase_offset = idx * (np.pi / 2.0) / max(n_grp - 1, 1) if n_grp > 1 else 0.0
            carrier_phases_arr[i] = _ratio_phase_start[r] + phase_offset
            _ratio_index[r] += 1
        self.carrier_phases = carrier_phases_arr % np.float32(2 * np.pi)
        # Nominal carrier phases (no drift) — tracked separately so that the
        # accumulated drift is continuous across chunks and can be applied once
        # to all harmonics without the h-fold amplification that would arise
        # from naively multiplying carrier_phases (which includes drift) by h.
        self.nominal_carrier_phases = self.carrier_phases.copy()
        self.mod_phases = np.zeros(n_voices, dtype=np.float32)
        self.drift_phases = np.array([random.uniform(0, 2 * np.pi) for _ in range(n_voices)], dtype=np.float32)

        # Precomputed angular frequencies
        self._mod_omega = np.float32(2 * np.pi) * self.mod_freqs
        self._drift_omega = np.float32(2 * np.pi) * self.drift_rates
        self._two_pi_dt = np.float32(2 * np.pi / self.SR)

        # Harmonic overtones
        self.harmonics = int(cfg.get("harmonics", 4))
        self.harmonic_decay = float(cfg.get("harmonic_decay", 0.7))

        # Filtered noise (breath texture)
        self.noise_amount = float(cfg.get("noise_amount", 0.0))
        self.noise_color = cfg.get("noise_color", "pink")
        self._noise_state = np.float32(0.0)  # 1-pole filter state for pink noise
        self._brown_state = np.float32(0.0)  # integrator state for brown noise

        # Voice stereo spread: each voice contributes to L as cos(θ) and to R as
        # sin(θ). θ=π/4 is the centre (equal L/R); voices spread symmetrically
        # around it. spread=0 → mono (all at π/4), spread=1 → default (π/8–3π/8),
        # spread=2 → full field (0–π/2).
        spread = float(cfg.get("spread", 1.0))
        center = np.float32(np.pi / 4)
        half_range = np.float32(np.clip(spread * np.pi / 8, 0.0, np.pi / 4))
        if n_voices > 1:
            self._voice_pan_angles = np.linspace(
                center - half_range, center + half_range, n_voices, dtype=np.float32
            )
        else:
            self._voice_pan_angles = np.array([center], dtype=np.float32)

        # Blend: amplitude taper across voices. blend=1 → all voices equal weight
        # (current); blend=0 → centre voice loudest, edge voices silent (pyramid
        # window). Allows layering where inner voices anchor the main pitch.
        blend = float(cfg.get("blend", 1.0))
        if n_voices > 1:
            norm_pos = np.linspace(-1.0, 1.0, n_voices, dtype=np.float32)
        else:
            norm_pos = np.zeros(1, dtype=np.float32)
        self._blend_weights = np.maximum(
            np.float32(1.0) - np.float32(1.0 - blend) * np.abs(norm_pos),
            np.float32(0.0),
        )

        # Volume: single dB gain replacing the old separate mix + loudness controls.
        # Backward-compatible: old presets now carry volume_db converted from mix.
        volume_db = float(cfg.get("volume_db", 0.0))
        self._gain = np.float32(10.0 ** (volume_db / 20.0))

        # Band filter
        self._setup_filter(cfg.get("band", "mid"))

    def _setup_filter(self, band: str) -> None:
        nyquist = self.SR * 0.5
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

        self.zi_L = sosfilt_zi(self.sos) * 0.0
        self.zi_R = sosfilt_zi(self.sos) * 0.0

    def next_chunk(self, n_samples: int) -> np.ndarray:
        dt = np.float32(1.0 / self.SR)
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

        # Nominal phases advance at pure carrier frequency (no drift).
        # drift_total = carrier_phases - nominal_phases accumulates continuously
        # across chunks (both state vars are updated at end of each chunk).
        # Using  h * nominal_phases + drift_total  for the h-th harmonic keeps
        # the absolute pitch deviation identical for every partial — the drift
        # is not amplified h-fold, preventing fast inter-voice beating in the
        # upper harmonics (e.g. 10 Hz tremolo at h=4 with drift=0.008).
        sample_indices = np.arange(1, n_samples + 1, dtype=np.float32)
        nominal_phases = self.nominal_carrier_phases[:, None] + (
            self._two_pi_dt * self.carrier_freqs[:, None] * sample_indices[None, :]
        )
        drift_total = carrier_phases - nominal_phases

        # Fundamental signal
        signal = np.sin(carrier_phases + modulator * self.fm_indices[:, None], dtype=np.float32)

        # Harmonic overtones — loop over harmonics (max 8), each vectorized
        if self.harmonics > 1:
            for h in range(2, self.harmonics + 1):
                harmonic_signal = np.sin(
                    nominal_phases * h + drift_total
                    + modulator * self.fm_indices[:, None] * (1.0 / h),
                    dtype=np.float32
                )
                signal += harmonic_signal * (self.harmonic_decay ** (h - 1))
            # Normalize so amplitude stays consistent regardless of harmonic count
            norm = 1.0 + sum(self.harmonic_decay ** (h - 1) for h in range(2, self.harmonics + 1))
            signal /= norm

        self.carrier_phases = carrier_phases[:, -1] % (2 * np.pi)
        self.nominal_carrier_phases = nominal_phases[:, -1] % (2 * np.pi)

        # Voice-spread stereo: each voice contributes to L/R based on its spread angle.
        # Blend weights taper amplitude from centre voices (weight=1) to edges (weight=blend).
        # Energy is preserved: sum(cos²+sin²)=n_voices, matching the mono dot-product power.
        L_weights = self.amplitudes * self._blend_weights * np.cos(self._voice_pan_angles)
        R_weights = self.amplitudes * self._blend_weights * np.sin(self._voice_pan_angles)
        layer_L = np.dot(L_weights, signal)  # shape (n_samples,)
        layer_R = np.dot(R_weights, signal)  # shape (n_samples,)

        # Filtered noise (breath texture) — applied before band filter
        if self.noise_amount > 0.0:
            noise = self._generate_noise(n_samples)
            amp_scale = np.mean(self.amplitudes)
            noise_scaled = noise * (self.noise_amount * amp_scale)
            layer_L = layer_L * (1.0 - self.noise_amount) + noise_scaled
            layer_R = layer_R * (1.0 - self.noise_amount) + noise_scaled

        # Apply band filter (stereo)
        filtered_L, self.zi_L = sosfilt(self.sos, layer_L, zi=self.zi_L)
        filtered_R, self.zi_R = sosfilt(self.sos, layer_R, zi=self.zi_R)
        return np.column_stack([filtered_L * self._gain, filtered_R * self._gain])

    def _generate_noise(self, n_samples: int) -> np.ndarray:
        """Generate colored noise (white, pink, or brown).

        Per-chunk peak normalization is intentionally NOT used here — dividing by
        chunk peak causes amplitude discontinuities at chunk boundaries (clicks),
        especially for pink/brown noise whose LF energy varies slowly.  Instead a
        fixed scale derived from the filter's steady-state RMS is applied so the
        output has consistent amplitude without any inter-chunk jumps.
        """
        white = np.random.randn(n_samples).astype(np.float32)
        if self.noise_color == "white":
            return white
        elif self.noise_color == "brown":
            # Brown noise: integrated white noise. a=0.998, gain=0.02
            # steady-state std ≈ 0.02/sqrt(1-0.998²) ≈ 0.316 → scale × 3.16 ≈ 1.0
            out = np.empty(n_samples, dtype=np.float32)
            state = self._brown_state
            for i in range(n_samples):
                state = state * 0.998 + white[i] * 0.02
                out[i] = state
            self._brown_state = state
            return out * np.float32(3.16)
        else:
            # Pink noise: 1-pole lowpass. a=0.94, gain=0.06
            # steady-state std ≈ 0.06/sqrt(1-0.94²) ≈ 0.176 → scale × 5.68 ≈ 1.0
            out = np.empty(n_samples, dtype=np.float32)
            state = self._noise_state
            alpha = np.float32(0.06)
            for i in range(n_samples):
                state = state * np.float32(0.94) + white[i] * alpha
                out[i] = state
            self._noise_state = state
            return out * np.float32(5.68)


class StreamingSubtractiveLayer:
    """
    Subtractive synthesis layer: waveform oscillators (saw/square/triangle)
    with optional dual-oscillator detune and sub-oscillator.
    Classic Reese bass and other filter-based drone textures.
    """

    def __init__(self, cfg: dict, sample_rate: int = None):
        self.SR = sample_rate or SR  # Use passed SR or fallback to module default
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

    def set_detune_cents(self, new_cents: float) -> None:
        """Smoothly update detune width. Scales existing osc freqs by the delta ratio."""
        if new_cents == self.detune_cents:
            return
        ratio = 2.0 ** ((new_cents - self.detune_cents) / 1200.0)
        self.osc1_freqs = (self.osc1_freqs * ratio).astype(np.float32)
        self.osc2_freqs = (self.osc2_freqs / ratio).astype(np.float32)
        self.detune_cents = new_cents

    def _waveform(self, phases: np.ndarray, freqs_hz: np.ndarray) -> np.ndarray:
        """Generate waveform samples from phase array (0..2pi).

        For the saw and square waves, a 2nd-order PolyBLEP correction is applied
        to band-limit the discontinuities.  Without it, the instantaneous jumps
        are amplified by distortion / saturation and appear as audible clicks.

        freqs_hz: (n_voices,) — needed to compute the per-voice phase
        increment (dt = f/SR) used by the PolyBLEP kernel.
        """
        p = phases % (2 * np.pi)
        if self.waveform == "triangle":
            return (
                np.float32(2.0)
                * np.abs(p / np.pi - np.floor(p / np.pi + np.float32(0.5)))
                * np.float32(2.0)
                - np.float32(1.0)
            ).astype(np.float32)

        t  = p / (2 * np.pi)                                  # (n_voices, n_samples)
        dt = np.clip(freqs_hz / self.SR, 1e-6, 0.5)[:, None]  # (n_voices, 1)

        def _polyblep(t_arr):
            """2nd-order PolyBLEP correction at t=0 transition."""
            lo  = t_arr < dt
            t_lo = t_arr / dt
            blep_lo = 2.0 * t_lo - t_lo * t_lo - 1.0     # 2t−t²−1  (−1 → 0)
            hi  = t_arr > (1.0 - dt)
            t_hi = (t_arr - 1.0) / dt
            blep_hi = t_hi * t_hi + 2.0 * t_hi + 1.0     # (t+1)²   ( 0 → +1)
            return np.where(lo, blep_lo, np.where(hi, blep_hi, 0.0))

        if self.waveform == "square":
            # Naive square: +1 for t<0.5, −1 for t≥0.5.
            # Two discontinuities per period:
            #   rising edge (+2 jump) at t=0   → add polyblep(t)
            #   falling edge (−2 jump) at t=0.5 → subtract polyblep((t−0.5)%1)
            sq = np.where(t < 0.5, 1.0, -1.0)
            t_fall = (t - 0.5) % 1.0
            correction = _polyblep(t) - _polyblep(t_fall)
            return (sq + correction).astype(np.float32)

        # ── Band-limited sawtooth with PolyBLEP correction ────────────────
        # t ∈ [0, 1) is the normalised phase; naive saw = 2t − 1.
        # PolyBLEP subtracts a small polynomial at each phase-reset boundary
        # so the waveform smoothly approaches 0 on both sides of the jump,
        # reducing the discontinuity from amplitude 2 to ~0.
        saw = 2.0 * t - 1.0
        correction = _polyblep(t)
        return (saw - correction).astype(np.float32)

    def next_chunk(self, n_samples: int) -> np.ndarray:
        dt = np.float32(1.0 / self.SR)
        t = np.arange(n_samples, dtype=np.float32) * dt

        drift_phases = self.drift_phases[:, None] + (2 * np.pi * self.drift_rates[:, None] * t[None, :])
        drift = np.sin(drift_phases, dtype=np.float32) * self.drift
        self.drift_phases = drift_phases[:, -1] % (2 * np.pi)

        inst_freq1 = self.osc1_freqs[:, None] * (1.0 + drift)
        phase_inc1 = 2 * np.pi * inst_freq1 * dt
        osc1_phases = self.osc1_phases[:, None] + np.cumsum(phase_inc1, axis=1)
        sig1 = self._waveform(osc1_phases, self.osc1_freqs)
        self.osc1_phases = osc1_phases[:, -1] % (2 * np.pi)

        inst_freq2 = self.osc2_freqs[:, None] * (1.0 + drift)
        phase_inc2 = 2 * np.pi * inst_freq2 * dt
        osc2_phases = self.osc2_phases[:, None] + np.cumsum(phase_inc2, axis=1)
        sig2 = self._waveform(osc2_phases, self.osc2_freqs)
        self.osc2_phases = osc2_phases[:, -1] % (2 * np.pi)

        combined = np.dot(self.amplitudes, (sig1 + sig2) * 0.5)

        sub_phases = self.sub_phase + 2 * np.pi * self.sub_freq * np.cumsum(np.ones(n_samples, dtype=np.float32) * dt)
        sub = np.sin(sub_phases, dtype=np.float32) * np.mean(self.amplitudes)
        self.sub_phase = sub_phases[-1] % (2 * np.pi)

        layer = combined * (1.0 - self.sub_mix) + sub * self.sub_mix
        _vol_db = float(self.cfg.get("volume_db", 0.0))
        return layer * np.float32(10.0 ** (_vol_db / 20.0))


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

    def _compute_pan(self, n: int) -> np.ndarray:
        """Compute per-sample pan positions [0, 1] and advance self.phase."""
        dt = 1.0 / SR
        t = self.phase + np.arange(n) * dt
        self.phase = float(t[-1]) + dt

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

        return np.clip(pan, 0.0, 1.0).astype(np.float32)

    def next_chunk(self, mono: np.ndarray) -> np.ndarray:
        """Equal-power pan for mono input (granular/subtractive layers)."""
        n = len(mono)
        pan = self._compute_pan(n)

        # Equal-power panning
        angle = pan * (np.pi / 2)
        left  = mono * np.cos(angle)
        right = mono * np.sin(angle)

        # Elevation processing (HRTF-like spectral filtering)
        current_elev = self._get_elevation_angle()
        self.elevation_phase += n / SR

        if abs(current_elev) > 0.5:
            elev_norm = np.clip(current_elev / 90.0, -1.0, 1.0)
            high_gain = 1.0 + elev_norm * 0.5
            low_gain  = 1.0 - elev_norm * 0.25

            low_L, self._lp_zi_L = sosfilt(self._lp_sos, left, zi=self._lp_zi_L)
            low_R, self._lp_zi_R = sosfilt(self._lp_sos, right, zi=self._lp_zi_R)
            high_L, self._hp_zi_L = sosfilt(self._hp_sos, left, zi=self._hp_zi_L)
            high_R, self._hp_zi_R = sosfilt(self._hp_sos, right, zi=self._hp_zi_R)

            left  = low_L * low_gain + high_L * high_gain
            right = low_R * low_gain + high_R * high_gain

        return np.column_stack([left, right])

    def _apply_balance(self, stereo: np.ndarray) -> np.ndarray:
        """Pan-shift for stereo input (FM layers with voice spread).

        Applies a linear balance fade: at pan=0 the right channel is silenced,
        at pan=1 the left channel is silenced, at pan=0.5 both are unchanged.
        This shifts the perceived stereo image without collapsing to mono.
        """
        n = len(stereo)
        pan = self._compute_pan(n)

        L_gain = np.minimum(np.float32(1.0), np.float32(2.0) * (1.0 - pan))
        R_gain = np.minimum(np.float32(1.0), np.float32(2.0) * pan)

        left  = stereo[:, 0] * L_gain
        right = stereo[:, 1] * R_gain

        # Elevation processing
        current_elev = self._get_elevation_angle()
        self.elevation_phase += n / SR

        if abs(current_elev) > 0.5:
            elev_norm = np.clip(current_elev / 90.0, -1.0, 1.0)
            high_gain = 1.0 + elev_norm * 0.5
            low_gain  = 1.0 - elev_norm * 0.25

            low_L, self._lp_zi_L = sosfilt(self._lp_sos, left, zi=self._lp_zi_L)
            low_R, self._lp_zi_R = sosfilt(self._lp_sos, right, zi=self._lp_zi_R)
            high_L, self._hp_zi_L = sosfilt(self._hp_sos, left, zi=self._hp_zi_L)
            high_R, self._hp_zi_R = sosfilt(self._hp_sos, right, zi=self._hp_zi_R)

            left  = low_L * low_gain + high_L * high_gain
            right = low_R * low_gain + high_R * high_gain

        return np.column_stack([left, right])

    def _apply_width(self, stereo: np.ndarray) -> np.ndarray:
        """Energy-preserving M/S width. width=0 → mono center, width=1 → original,
        width=2 → extra-wide.  Normalization keeps power constant for uncorrelated L/R."""
        w = self.width
        if abs(w - 1.0) < 0.01:
            return stereo
        mid  = (stereo[:, 0] + stereo[:, 1]) * np.float32(0.5)
        side = (stereo[:, 0] - stereo[:, 1]) * np.float32(0.5)
        # sqrt((1+w²)/2) preserves energy when L and R are uncorrelated
        norm = np.float32(np.sqrt((1.0 + w * w) * 0.5))
        L_out = (mid + side * w) / norm
        R_out = (mid - side * w) / norm
        return np.column_stack([L_out, R_out])

    def process(self, layer_out: np.ndarray) -> np.ndarray:
        """Pan + width. Accepts mono (granular/subtractive) or stereo (FM voice spread)."""
        if layer_out.ndim == 1:
            return self._apply_width(self.next_chunk(layer_out))
        else:
            return self._apply_width(self._apply_balance(layer_out))


# ── Streaming Chorus ──────────────────────────────────────────────────────────

class StreamingChorus:
    """Per-layer stereo chorus with modulated delay lines."""

    def __init__(self, rate=0.5, depth=0.005, mix=0.0, voices=2):
        self.rate = float(rate)
        self.depth = float(depth)
        self.mix = float(mix)
        self.n_voices = int(voices)
        # center_delay must exceed depth_samples so the modulated delay never
        # goes negative (negative delay wraps the circular buffer to stale audio
        # thousands of samples old, causing loud clicks).
        depth_samples = int(self.depth * SR) + 1
        self.center_delay = max(int(0.015 * SR), depth_samples + 16)
        self.max_delay = max(int(0.03 * SR) + 1, self.center_delay + depth_samples + 16)
        self.buffer_size = self.max_delay + 8192
        self.buf_L = np.zeros(self.buffer_size, dtype=np.float32)
        self.buf_R = np.zeros(self.buffer_size, dtype=np.float32)
        self.write_pos = 0
        self.lfo_phases = np.linspace(0, 2 * np.pi, self.n_voices, endpoint=False)

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
            delay = np.maximum(self.center_delay + mod, 1.0)  # clamp: never negative

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

    def next_chunk(self, audio: np.ndarray) -> np.ndarray:
        """Filter audio. Accepts mono (n,) or stereo (n,2); returns the same shape."""
        is_mono = (audio.ndim == 1)
        stereo = np.column_stack([audio, audio]) if is_mono else audio
        if self.filter_type == "comb":
            result = self._next_chunk_comb(stereo)
        elif self.filter_type == "formant":
            result = self._next_chunk_formant(stereo)
        elif self.filter_type == "off" or self._sos is None:
            result = stereo
        else:
            n = len(stereo)
            if self.lfo_depth > 0.001:
                lfo_val = self._lfo_value(n)
                octaves = lfo_val * self.lfo_depth * 2.0
                modulated_cutoff = self.base_cutoff * (2.0 ** octaves)
                self._build_filter(modulated_cutoff)
            else:
                self._lfo_value(n)
            if self._sos is None:
                result = stereo
            else:
                filtered_L, self._zi_L = sosfilt(self._sos, stereo[:, 0], zi=self._zi_L)
                filtered_R, self._zi_R = sosfilt(self._sos, stereo[:, 1], zi=self._zi_R)
                result = np.stack([filtered_L, filtered_R], axis=1).astype(np.float32)
        return result[:, 0] if is_mono else result


# ── Shimmer ───────────────────────────────────────────────────────────────────

class StreamingShimmer:
    """
    Global shimmer effect: pitch-shifted feedback layer on the full stereo mix.

    Two staggered read heads scan a circular buffer at speed 2^(semitones/12).
    Hann-window cross-fading between heads ensures the amplitude sum is always
    exactly 1.0 (sin²(θ) + cos²(θ) = 1), so there are no volume bumps or gaps.
    Feedback re-injects the shimmer output into the write buffer, building an
    ethereal, self-sustaining tail.

    Typical use: wet=0.3, pitch_semitones=12, feedback=0.5 → classic octave shimmer.
    """

    def __init__(
        self,
        wet: float = 0.0,
        pitch_semitones: float = 12.0,
        feedback: float = 0.5,
    ):
        self.wet      = float(wet)
        self.feedback = float(np.clip(feedback, 0.0, 0.95))
        self._speed   = 2.0 ** (float(pitch_semitones) / 12.0)

        # Circular buffer ≈ 200 ms, next power-of-2 for fast modulo
        N = 1 << int(np.ceil(np.log2(max(SR * 0.20, 1))))
        self._N   = N
        self._buf = np.zeros((N, 2), dtype=np.float64)

        # Two read heads staggered by N/2 so their Hann windows always sum to 1
        self._read  = [0.0, N / 2.0]
        self._write = 0

    def next_chunk(self, stereo: np.ndarray) -> np.ndarray:
        if self.wet < 0.001:
            return stereo

        n   = len(stereo)
        N   = self._N
        buf = self._buf

        # Write input into circular buffer
        w_idx = (self._write + np.arange(n)) % N
        buf[w_idx] = stereo.astype(np.float64)

        # Accumulate shimmer from both read heads
        shimmer = np.zeros((n, 2), dtype=np.float64)
        for h in range(2):
            pos = (self._read[h] + np.arange(n) * self._speed) % N

            # Linear interpolation across circular buffer
            i0  = pos.astype(np.int64) % N
            i1  = (i0 + 1) % N
            fr  = (pos - np.floor(pos))[:, None]
            smp = buf[i0] * (1.0 - fr) + buf[i1] * fr

            # Hann window: sin²(π * phase), peaks at phase=0.5, zeroes at 0 and 1
            # Head 0 (phase) and head 1 (phase+0.5) sum to exactly 1.0 always
            phase  = (pos % N) / N
            window = np.sin(np.pi * phase) ** 2

            shimmer += smp * window[:, None]
            self._read[h] = (self._read[h] + n * self._speed) % N

        # Feedback: write shimmer back into buffer for next chunk's input
        buf[w_idx] += shimmer * self.feedback

        self._write = (self._write + n) % N

        result = stereo.astype(np.float64) * (1.0 - self.wet) + shimmer * self.wet
        return result.astype(np.float32)

    def copy_state(self):
        s = StreamingShimmer.__new__(StreamingShimmer)
        s.wet      = self.wet
        s.feedback = self.feedback
        s._speed   = self._speed
        s._N       = self._N
        s._buf     = self._buf.copy()
        s._read    = list(self._read)
        s._write   = self._write
        return s


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

        # LFO: precompute delay in samples for every sample in the chunk
        lfo_inc  = 2.0 * np.pi * self.rate / SR
        phases   = self.lfo_phase + lfo_inc * np.arange(n, dtype=np.float64)
        center   = self._min_delay + self._max_mod * 0.5
        delay_s  = center + np.sin(phases) * (self._max_mod * 0.5 * self.depth)

        # Process sample-by-sample so feedback is continuous (not once-per-chunk).
        # A per-chunk approach caused a periodic kick at the chunk rate (~10.8 Hz)
        # that, filtered by the comb, produced an audible buzz in the 1-2 kHz band.
        out_L = np.empty(n, dtype=np.float32)
        out_R = np.empty(n, dtype=np.float32)
        fb_L = self._fb_L
        fb_R = self._fb_R
        buf_sz = self._buf_sz
        buf_L  = self._buf_L
        buf_R  = self._buf_R
        wr     = self._write

        for i in range(n):
            buf_L[wr] = stereo[i, 0] + fb * fb_L
            buf_R[wr] = stereo[i, 1] + fb * fb_R

            rp  = (wr - delay_s[i]) % buf_sz
            r0  = int(rp) % buf_sz
            r1  = (r0 + 1) % buf_sz
            f   = float(rp - int(rp))
            wl  = buf_L[r0] * (1.0 - f) + buf_L[r1] * f
            wr_ = buf_R[r0] * (1.0 - f) + buf_R[r1] * f

            out_L[i] = wl
            out_R[i] = wr_
            fb_L = wl
            fb_R = wr_
            wr = (wr + 1) % buf_sz

        self._fb_L    = fb_L
        self._fb_R    = fb_R
        self._write   = wr
        self.lfo_phase = float((phases[-1] + lfo_inc) % (2.0 * np.pi))

        out = stereo.copy()
        out[:, 0] = stereo[:, 0] * (1.0 - self.wet) + out_L * self.wet
        out[:, 1] = stereo[:, 1] * (1.0 - self.wet) + out_R * self.wet
        return out.astype(np.float32)


class StreamingPhaser:
    """Per-layer all-pass chain phaser with LFO-swept center frequency.

    Uses N first-order all-pass stages in series. The LFO modulates
    the all-pass coefficient (= cutoff frequency), sweeping comb-like
    notches through the spectrum. L and R LFO phases are offset by 90°
    for natural stereo width without a separate width parameter.

    All-pass difference equation: y[n] = a*x[n] + x[n-1] - a*y[n-1]
    coefficient: a = (tan(π*f/SR) - 1) / (tan(π*f/SR) + 1)
    """

    def __init__(self, rate: float = 0.5, depth: float = 0.7,
                 center_hz: float = 800.0, feedback: float = 0.0,
                 wet: float = 0.0, stages: int = 4):
        self.rate      = float(rate)
        self.depth     = float(depth)
        self.center_hz = float(center_hz)
        self.feedback  = float(np.clip(feedback, -0.95, 0.95))
        self.wet       = float(wet)
        self.stages    = int(np.clip(stages, 2, 12))
        self.lfo_phase = 0.0
        # Per-stage all-pass states: previous input and output for each stage
        self._xp_L = np.zeros(self.stages, dtype=np.float64)
        self._yp_L = np.zeros(self.stages, dtype=np.float64)
        self._xp_R = np.zeros(self.stages, dtype=np.float64)
        self._yp_R = np.zeros(self.stages, dtype=np.float64)
        self._fb_L = 0.0
        self._fb_R = 0.0

    def next_chunk(self, stereo: np.ndarray) -> np.ndarray:
        if self.wet < 0.001:
            return stereo
        n = len(stereo)
        S = self.stages

        # LFO: L and R offset by 90° for stereo width
        lfo_inc = 2.0 * np.pi * self.rate / SR
        ph = self.lfo_phase + lfo_inc * np.arange(n, dtype=np.float64)
        ph_R = ph + np.pi * 0.5

        # Instantaneous center frequency, clamped to safe range
        f_L = np.clip(self.center_hz * (1.0 + np.sin(ph) * self.depth), 20.0, SR * 0.45)
        f_R = np.clip(self.center_hz * (1.0 + np.sin(ph_R) * self.depth), 20.0, SR * 0.45)

        # All-pass coefficient a per sample
        t_L = np.tan(np.pi * f_L / SR)
        t_R = np.tan(np.pi * f_R / SR)
        a_L = (t_L - 1.0) / (t_L + 1.0)
        a_R = (t_R - 1.0) / (t_R + 1.0)

        fb    = float(np.clip(self.feedback, -0.95, 0.95))
        xp_L  = self._xp_L.copy()
        yp_L  = self._yp_L.copy()
        xp_R  = self._xp_R.copy()
        yp_R  = self._yp_R.copy()
        fb_L  = self._fb_L
        fb_R  = self._fb_R

        out_L = np.empty(n, dtype=np.float32)
        out_R = np.empty(n, dtype=np.float32)

        for i in range(n):
            aL = a_L[i]
            aR = a_R[i]

            # Input with feedback
            xL = float(stereo[i, 0]) + fb * fb_L
            xR = float(stereo[i, 1]) + fb * fb_R

            # All-pass chain L: y[n] = a*x[n] + x[n-1] - a*y[n-1]
            for s in range(S):
                y = aL * xL + xp_L[s] - aL * yp_L[s]
                xp_L[s] = xL
                yp_L[s] = y
                xL = y

            # All-pass chain R
            for s in range(S):
                y = aR * xR + xp_R[s] - aR * yp_R[s]
                xp_R[s] = xR
                yp_R[s] = y
                xR = y

            out_L[i] = xL
            out_R[i] = xR
            fb_L = xL
            fb_R = xR

        self._xp_L = xp_L;  self._yp_L = yp_L
        self._xp_R = xp_R;  self._yp_R = yp_R
        self._fb_L = fb_L;  self._fb_R = fb_R
        self.lfo_phase = float((ph[-1] + lfo_inc) % (2.0 * np.pi))

        out = stereo.copy()
        out[:, 0] = stereo[:, 0] * (1.0 - self.wet) + out_L * self.wet
        out[:, 1] = stereo[:, 1] * (1.0 - self.wet) + out_R * self.wet
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
    _BASE_SR       = 22050  # Sample rate the delay tables are tuned for
    _MAX_PRE_DELAY_MS = 150.0  # Maximum pre-delay in milliseconds

    def __init__(self, reverb_cfg: dict, sample_rate: int = None):
        self.SR = sample_rate or SR  # Use passed SR or fallback to module default
        self.enabled = bool(reverb_cfg.get("enabled", False))
        self.mix     = float(reverb_cfg.get("mix", 0.3))

        # Map decay_trim (0.0–1.0) → feedback gain (0.60–0.96). Values >1.0
        # would make the FDN unstable (feedback > 1), so clamp defensively.
        decay_trim  = float(np.clip(reverb_cfg.get("decay_trim", 1.0), 0.0, 1.0))
        self.decay  = 0.60 + decay_trim * 0.36

        # Pre-delay
        self.pre_delay_ms      = float(reverb_cfg.get("pre_delay_ms", 0.0))
        self._MAX_PRE_DELAY = int(self._MAX_PRE_DELAY_MS * self.SR / 1000.0)
        self._pre_delay_samps  = min(
            int(self.pre_delay_ms * self.SR / 1000.0), self._MAX_PRE_DELAY
        )

        # Modulation depth (0–1 → 0–5 samples swing)
        self.mod_depth = float(reverb_cfg.get("modulation_depth", 0.0))
        self._LFO_DEPTH_MAX = 5.0  # Maximum LFO swing in samples

        # Choose space and scale delays for target sample rate
        # MANT-1: Scale delay tables from base 22050 Hz to target SR
        space = reverb_cfg.get("space", "cathedral")
        base_delays = self._SPACES.get(space, self._SPACES["cathedral"])
        scale_factor = self.SR / self._BASE_SR
        self.delays = np.array(
            [int(d * scale_factor) for d in base_delays], dtype=np.int32
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

        # Pre-delay FIFO — sized generously so any chunk ≤ _MAX_CHUNK works.
        # The FIFO stores the last (pd + _MAX_CHUNK) samples; fdn_in is the
        # oldest n samples (i.e. delayed by pd).
        # R2: Stereo buffers for independent L/R processing
        _MAX_CHUNK = 8192
        self._pre_fifo_L = np.zeros(self._pre_delay_samps + _MAX_CHUNK, dtype=np.float64)
        self._pre_fifo_R = np.zeros(self._pre_delay_samps + _MAX_CHUNK, dtype=np.float64)

        # Per-line LFO state
        rng = np.random.default_rng(seed=42)
        self._lfo_phases = rng.uniform(0.0, 2 * np.pi, self._N_LINES)
        self._lfo_rates  = rng.uniform(0.1, 0.5, self._N_LINES)   # Hz

    # ------------------------------------------------------------------

    def copy_state(self) -> "StreamingFDNReverb":
        """Deep-copy mutable state for crossfade old_engine."""
        import copy
        clone = copy.copy(self)
        clone.buf         = self.buf.copy()
        clone._damp_zi    = self._damp_zi.copy()
        clone._pre_fifo_L = self._pre_fifo_L.copy()  # R2: Stereo buffers
        clone._pre_fifo_R = self._pre_fifo_R.copy()
        clone._lfo_phases = self._lfo_phases.copy()
        clone._lfo_rates  = self._lfo_rates.copy()
        return clone

    # ------------------------------------------------------------------

    def next_chunk(self, stereo: np.ndarray) -> np.ndarray:
        """Apply FDN reverb to stereo chunk (N, 2). Returns same shape."""
        if not self.enabled or self.mix < 0.001:
            return stereo

        n = len(stereo)
        # Stereo reverb: process L and R independently with small cross-coupling
        in_L = stereo[:, 0].astype(np.float64)
        in_R = stereo[:, 1].astype(np.float64)

        # ── Pre-delay ────────────────────────────────────────────────────
        # R2: Process L and R independently through pre-delay
        pd = self._pre_delay_samps
        if pd > 0:
            # FIFO shift: oldest n samples become fdn_in; new stereo appended
            fdn_in_L = self._pre_fifo_L[:n].copy()
            fdn_in_R = self._pre_fifo_R[:n].copy()
            self._pre_fifo_L[:-n] = self._pre_fifo_L[n:]
            self._pre_fifo_R[:-n] = self._pre_fifo_R[n:]
            self._pre_fifo_L[-n:] = in_L
            self._pre_fifo_R[-n:] = in_R
        else:
            fdn_in_L = in_L
            fdn_in_R = in_R

        # ── LFO: advance phases, compute per-line delay offsets (per chunk) ─
        dt = n / self.SR
        self._lfo_phases += 2.0 * np.pi * self._lfo_rates * dt
        lfo_off = (np.sin(self._lfo_phases) * self._lfo_depth_max
                   * self.mod_depth).astype(np.int32)

        # ── Read from all 8 delay lines using vectorised fancy indexing ─────
        # Robust for any n ≤ max_d; no branch needed for wrap-around.
        v = np.empty((self._N_LINES, n), dtype=np.float64)
        arange_n = np.arange(n)
        for j in range(self._N_LINES):
            d_j = int(self.delays[j]) + int(lfo_off[j])
            d_j = max(n + 1, min(d_j, self.max_d - 1))
            rs  = (self.write_ptr - d_j) % self.max_d
            v[j] = self.buf[j].take((rs + arange_n) % self.max_d)

        # ── Hadamard mix + input injection ───────────────────────────────
        # R2: Split input to L and R, with small cross-coupling for coherence
        u = self._H8d @ v                          # (8, n) vectorised
        u += fdn_in_L[np.newaxis, :] * 0.125         # L input to even lines
        u += fdn_in_R[np.newaxis, :] * 0.125         # R input to odd lines

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
    """Per-layer waveshaper distortion (soft-clip tanh or hard-clip).

    When drive > 0 a 4th-order 5 kHz anti-aliasing LP filter is applied
    after the waveshaper.  Nonlinear distortion folds the PolyBLEP residual
    discontinuities of saw/square oscillators into wideband energy; the LP
    removes that high-frequency artefact without audibly affecting the drone's
    harmonic content (fundamentals and low-order harmonics stay below 5 kHz).
    """

    def __init__(self, drive: float = 0.0, dist_type: str = "soft"):
        self.drive = float(drive)
        self.dist_type = dist_type
        # Anti-aliasing state (only allocated when distortion is active)
        if self.drive > 0.0:
            nyquist = SR * 0.5
            self._aa_sos = butter(4, min(5000.0 / nyquist, 0.999),
                                  btype="low", output="sos")
            self._aa_zi_l = sosfilt_zi(self._aa_sos) * 0.0
            self._aa_zi_r = sosfilt_zi(self._aa_sos) * 0.0
        else:
            self._aa_sos = None

    def process(self, audio: np.ndarray) -> np.ndarray:
        """Distort audio. Accepts mono (n,) or stereo (n,2); returns the same shape."""
        is_mono = (audio.ndim == 1)
        stereo = np.column_stack([audio, audio]) if is_mono else audio
        if self.drive < 0.01:
            return audio
        
        d = 1.0 + self.drive * 4.0
        
        # R3: Use oversampling for waveshapers to reduce aliasing
        def waveshaper(x):
            if self.dist_type == "hard":
                return np.clip(x * d, -1.0, 1.0) / d
            else:  # soft (tanh)
                return np.tanh(x * d) / np.tanh(d)
        
        # Apply waveshaper directly (oversampling removed - caused clicks at chunk boundaries)
        out = waveshaper(stereo)
        
        # Post-waveshaper anti-aliasing filter (still useful for PolyBLEP residuals)
        if self._aa_sos is not None:
            out[:, 0], self._aa_zi_l = sosfilt(self._aa_sos, out[:, 0], zi=self._aa_zi_l)
            out[:, 1], self._aa_zi_r = sosfilt(self._aa_sos, out[:, 1], zi=self._aa_zi_r)
        
        return out[:, 0] if is_mono else out


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

    def __init__(self, preset: dict, seed: int = 42, render_mode: bool = False):
        self.chunk_size = 2048
        self.render_mode = render_mode  # disables per-chunk peak scaler for offline renders
        # MANT-1: Auto-select sample rate based on render_mode
        # Preview: 22050 Hz (CPU efficient), Render: 48000 Hz (full quality)
        self.SR = config.SAMPLE_RATE if render_mode else config.STREAM_SAMPLE_RATE
        self._limiter_gain = 1.0        # stateful gain carried across chunks
        # Seed random state for reproducible preview
        random.seed(seed)
        np.random.seed(seed)
        self._seed = seed
        # Automation time tracking
        self._samples_elapsed: int = 0
        self._duration_samples: int = 0  # set from preset duration; 0 = unknown
        # MANT-9: previous automated values for intra-chunk interpolation
        self._prev_layer_auto = {}  # dict of {layer_idx: {param: prev_value}}
        self._prev_global_auto = {}  # dict of {param: prev_value}
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
        self.flangers = []
        self.phasers = []
        self._peak_meters = []   # per-layer peak in dBFS, smoothly decaying
        self.saturation = float(preset.get("saturation", 0.3))
        self._master = MasterProcessor(preset.get("master", {}), self.SR)

        # Reset automation time on preset rebuild
        self._samples_elapsed = 0
        duration_secs = float(preset.get("duration", 0))
        self._duration_samples = int(duration_secs * self.SR) if duration_secs > 0 else 0

        # JI tuning: derive each layer's root from a single tonic
        tuning_mode = preset.get("tuning_mode", "free")
        if tuning_mode == "ji":
            from .tuning import get_ji_hz
            tonic_hz   = float(preset.get("tonic_hz", 432.0))
            ji_system  = preset.get("tuning_system_ji", "5limit_ji")
            pure_mode  = bool(preset.get("pure_mode", False))
            resolved = []
            for lc in preset["layers"]:
                lc = dict(lc)  # shallow copy — never mutate the original preset
                degree = lc.get("tuning_degree", "unison")
                lc["root"] = get_ji_hz(tonic_hz, ji_system, degree)
                if pure_mode:
                    lc["detune_cents"] = 0.0
                resolved.append(lc)
            preset = {**preset, "layers": resolved}

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
                layer = StreamingGranularLayer(resolved_cfg, samples_dir, sample_rate=self.SR)
            elif layer_cfg.get("type") == "subtractive":
                layer = StreamingSubtractiveLayer(layer_cfg, sample_rate=self.SR)
            else:
                layer = StreamingLayer(layer_cfg, sample_rate=self.SR)
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
            self.flangers.append(StreamingFlanger(
                rate=float(layer_cfg.get("flanger_rate", 0.25)),
                depth=float(layer_cfg.get("flanger_depth", 0.5)),
                feedback=float(layer_cfg.get("flanger_feedback", 0.4)),
                wet=float(layer_cfg.get("flanger_wet", 0.0)),
            ))
            self.phasers.append(StreamingPhaser(
                rate=float(layer_cfg.get("phaser_rate", 0.5)),
                depth=float(layer_cfg.get("phaser_depth", 0.7)),
                center_hz=float(layer_cfg.get("phaser_center_hz", 800.0)),
                feedback=float(layer_cfg.get("phaser_feedback", 0.0)),
                wet=float(layer_cfg.get("phaser_wet", 0.0)),
                stages=int(layer_cfg.get("phaser_stages", 4)),
            ))

        # Earth engine (simple streaming sine)
        self.earth_cfg = preset.get("earth")
        self.earth_phase = 0.0
        self.earth_wobble_phase = 0.0
        self._earth_delay_buf = np.zeros(4, dtype=np.float32)  # R2: Stereo decorrelation buffer

        # Air engine (streaming noise)
        self.air_cfg = preset.get("air")
        self._air_kernel = int(0.1 * self.SR)
        self._air_state = np.float32(0.0)  # EMA state carried across chunks (was _air_buffer[-1] = always 0)

        # DC block filter state
        nyquist = self.SR * 0.5
        self._dc_sos = butter(4, max(18 / nyquist, 0.001), btype="high", output="sos")
        self._dc_zi_L = sosfilt_zi(self._dc_sos) * 0.0
        self._dc_zi_R = sosfilt_zi(self._dc_sos) * 0.0

        # Global FDN reverb
        self._reverb = StreamingFDNReverb(preset.get("reverb") or {}, sample_rate=self.SR)

        # Global shimmer
        shimmer_cfg = preset.get("shimmer") or {}
        self._shimmer = StreamingShimmer(
            wet=float(shimmer_cfg.get("wet", 0.0)),
            pitch_semitones=float(shimmer_cfg.get("pitch_semitones", 12.0)),
            feedback=float(shimmer_cfg.get("feedback", 0.5)),
        )

        # Streaming binaural — applied post-chain as the very last effect
        self._binaural_cfg = preset.get("binaural") or {}
        self._binaural_t   = 0  # sample counter for drift-free phase

        # Automation curves — parsed from preset, applied per-chunk
        # _layer_automations: list parallel to self.layers
        # _global_automations: dict keyed by GLOBAL_AUTO_PARAMS keys
        active_layer_cfgs = [
            cfg for cfg in preset.get("layers", []) if not cfg.get("muted", False)
        ]
        self._layer_automations = [
            parse_layer_automation(cfg, seed=self._seed) for cfg in active_layer_cfgs
        ]
        self._global_automations = parse_global_automation(preset, seed=self._seed)

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
            self._crossfade_total = int(crossfade_secs * self.SR)
            self._crossfade_remaining = self._crossfade_total
            self._build_from_preset(new_preset)

        stereo = np.zeros((n, 2), dtype=np.float32)

        # Apply parameter automation before generating this chunk
        # MANT-9: compute interpolation ramps for automated parameters
        automation_ramps = {}
        if self._duration_samples > 0 and (self._layer_automations or self._global_automations):
            t_norm = min(1.0, self._samples_elapsed / self._duration_samples)
            automation_ramps = self._compute_automation_ramps(t_norm, n)

        # Layers — signal chain: Synthesis → Filter → Distortion → Pan → Chorus → Flanger → Phaser
        for i, (layer, panner, chorus, layer_filter, distortion, flanger, phaser) in enumerate(zip(
            self.layers, self.panners, self.choruses, self.filters,
            self.distortions, self.flangers, self.phasers
        )):
            # MANT-9: apply per-layer automation ramps for this layer
            self._apply_layer_ramps(i, layer, layer_filter, distortion, panner, automation_ramps, n)
            
            raw      = layer.next_chunk(n)          # mono (sub/gran) or stereo (fm)
            filtered = layer_filter.next_chunk(raw) # tone shaping on raw signal
            distorted = distortion.process(filtered) # drive on shaped signal
            panned   = panner.process(distorted)    # place in stereo field
            chorused = chorus.next_chunk(panned)    # widen/animate
            flanged  = flanger.next_chunk(chorused)
            phased   = phaser.next_chunk(flanged)
            stereo  += phased
            # Peak meter: track per-layer peak with ~1.5 dB/chunk decay (~15 dB/sec)
            chunk_peak_db = 20.0 * np.log10(float(np.max(np.abs(phased))) + 1e-9)
            if i < len(self._peak_meters):
                self._peak_meters[i] = max(chunk_peak_db, self._peak_meters[i] - 1.5)
            else:
                self._peak_meters.append(chunk_peak_db)

        # DC block (on drone mix only)
        stereo[:, 0], self._dc_zi_L = sosfilt(self._dc_sos, stereo[:, 0], zi=self._dc_zi_L)
        stereo[:, 1], self._dc_zi_R = sosfilt(self._dc_sos, stereo[:, 1], zi=self._dc_zi_R)

        # Soft saturation (warm analog-style tanh waveshaping)
        # MANT-9: apply global automation for saturation
        if automation_ramps and "saturation" in automation_ramps.get('global', {}):
            self.saturation = float(automation_ramps['global']["saturation"])
        if self.saturation > 0.01:
            drive = 1.0 + self.saturation * 3.0
            norm = np.tanh(drive)
            
            # Apply global saturation (oversampling removed - caused clicks at chunk boundaries)
            stereo = np.tanh(stereo * drive) / norm

        # FDN reverb — only processes synthesized drone layers
        # MANT-9: apply global automation for reverb
        if automation_ramps:
            g_ramps = automation_ramps.get('global', {})
            if "reverb_mix" in g_ramps:
                self._reverb.mix = g_ramps["reverb_mix"]
            if "reverb_decay_trim" in g_ramps:
                trim = g_ramps["reverb_decay_trim"]
                self._reverb.decay = 0.60 + float(np.clip(trim, 0.0, 1.0)) * 0.36
        stereo = self._reverb.next_chunk(stereo)

        # Shimmer — pitch-shifted feedback layer, post-reverb
        if automation_ramps and "shimmer_wet" in automation_ramps.get('global', {}):
            self._shimmer.wet = automation_ramps['global']["shimmer_wet"]
        stereo = self._shimmer.next_chunk(stereo)

        # Earth & Air added post-reverb — environmental constants, kept dry
        if self.earth_cfg and self.earth_cfg.get("enabled", True):
            stereo += self._earth_chunk(n)
        if self.air_cfg and self.air_cfg.get("enabled", True):
            stereo += self._air_chunk(n)

        # Master EQ + compression
        if automation_ramps:
            g_ramps = automation_ramps.get('global', {})
            if "master_air_db" in g_ramps:
                self._master.set_air_db(g_ramps["master_air_db"])
            if "master_output_db" in g_ramps:
                self._master.set_output_gain_db(g_ramps["master_output_db"])
        stereo = self._master.process(stereo)

        # Soft limiter — streaming only; render path uses full-buffer final_limit_normalize
        if not self.render_mode:
            peak = float(np.max(np.abs(stereo)))
            target = min(1.0, 0.92 / peak) if peak > 1e-6 else 1.0
            # Ramp gain smoothly across the chunk — no sudden step at chunk boundary
            gain_ramp = np.linspace(self._limiter_gain, target, stereo.shape[0], dtype=np.float64)
            stereo = stereo * gain_ramp[:, np.newaxis]
            self._limiter_gain = target

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

        # Binaural — absolutely last: psychoacoustic L/R difference must reach headphones unprocessed
        if automation_ramps and "binaural_beat_hz" in automation_ramps.get('global', {}):
            self._binaural_cfg["beat_hz"] = automation_ramps['global']["binaural_beat_hz"]
        self._apply_binaural(stereo, n)

        # Advance automation time counter
        self._samples_elapsed += n

        return stereo

    def _compute_automation_ramps(self, t_norm: float, n: int) -> dict:
        """MANT-9: Compute interpolation ramps for automated parameters.
        
        Returns dict with structure:
        {
            'layer': {layer_idx: {param_name: np.ndarray}},
            'global': {param_name: (prev_val, curr_val)}
        }
        """
        ramps = {'layer': {}, 'global': {}}
        
        # Per-layer automations
        for i, auto in enumerate(self._layer_automations):
            if not auto:
                continue
            
            layer_ramps = {}
            
            # Filter cutoff — needs intra-chunk interpolation to avoid clicks
            if "filter_cutoff" in auto:
                curr = auto["filter_cutoff"].value_at(t_norm)
                prev = self._prev_layer_auto.get(i, {}).get("filter_cutoff", curr)
                layer_ramps["filter_cutoff"] = np.linspace(prev, curr, n, dtype=np.float32)
                if i not in self._prev_layer_auto:
                    self._prev_layer_auto[i] = {}
                self._prev_layer_auto[i]["filter_cutoff"] = curr
            
            # Volume — interpolate to avoid zipper noise
            if "volume_db" in auto:
                curr = auto["volume_db"].value_at(t_norm)
                prev = self._prev_layer_auto.get(i, {}).get("volume_db", curr)
                layer_ramps["volume_db"] = np.linspace(prev, curr, n, dtype=np.float32)
                if i not in self._prev_layer_auto:
                    self._prev_layer_auto[i] = {}
                self._prev_layer_auto[i]["volume_db"] = curr
            
            # FM index — smooth timbre transitions
            if "fm_index" in auto:
                curr = auto["fm_index"].value_at(t_norm)
                prev = self._prev_layer_auto.get(i, {}).get("fm_index", curr)
                layer_ramps["fm_index"] = np.linspace(prev, curr, n, dtype=np.float32)
                if i not in self._prev_layer_auto:
                    self._prev_layer_auto[i] = {}
                self._prev_layer_auto[i]["fm_index"] = curr
            
            # Width — smooth stereo field changes
            if "width" in auto:
                curr = auto["width"].value_at(t_norm)
                prev = self._prev_layer_auto.get(i, {}).get("width", curr)
                layer_ramps["width"] = np.linspace(prev, curr, n, dtype=np.float32)
                if i not in self._prev_layer_auto:
                    self._prev_layer_auto[i] = {}
                self._prev_layer_auto[i]["width"] = curr
            
            # Other parameters (not click-prone, apply once per chunk)
            if "distortion_drive" in auto:
                layer_ramps["distortion_drive"] = auto["distortion_drive"].value_at(t_norm)
            if "chorus_rate" in auto:
                layer_ramps["chorus_rate"] = auto["chorus_rate"].value_at(t_norm)
            if "lfo_rate" in auto:
                layer_ramps["lfo_rate"] = auto["lfo_rate"].value_at(t_norm)
            if "detune_cents" in auto:
                layer_ramps["detune_cents"] = auto["detune_cents"].value_at(t_norm)
            if "granular_position" in auto:
                layer_ramps["granular_position"] = auto["granular_position"].value_at(t_norm)
            
            if layer_ramps:
                ramps['layer'][i] = layer_ramps
        
        # Global automations (applied in main chain, not during layer processing)
        g = self._global_automations
        if g:
            if "reverb_mix" in g:
                ramps['global']["reverb_mix"] = g["reverb_mix"].value_at(t_norm)
            if "reverb_decay_trim" in g:
                ramps['global']["reverb_decay_trim"] = g["reverb_decay_trim"].value_at(t_norm)
            if "shimmer_wet" in g:
                ramps['global']["shimmer_wet"] = g["shimmer_wet"].value_at(t_norm)
            if "binaural_beat_hz" in g:
                ramps['global']["binaural_beat_hz"] = g["binaural_beat_hz"].value_at(t_norm)
            if "master_air_db" in g:
                ramps['global']["master_air_db"] = g["master_air_db"].value_at(t_norm)
            if "master_output_db" in g:
                ramps['global']["master_output_db"] = g["master_output_db"].value_at(t_norm)
            if "saturation" in g:
                ramps['global']["saturation"] = float(np.clip(g["saturation"].value_at(t_norm), 0.0, 1.0))
        
        return ramps
    
    def _apply_layer_ramps(self, i: int, layer, layer_filter, distortion, panner, ramps: dict, n: int) -> None:
        """MANT-9: Apply interpolated parameter ramps for a specific layer."""
        layer_ramps = ramps['layer'].get(i, {})
        if not layer_ramps:
            return
        
        # Filter cutoff — process in sub-blocks to smooth coefficient changes
        if "filter_cutoff" in layer_ramps and layer_filter.filter_type not in ("off", "comb", "formant"):
            cutoff_ramp = layer_ramps["filter_cutoff"]
            # Sub-block size: balance between smoothness and CPU cost
            sub_block_size = 256
            for block_start in range(0, n, sub_block_size):
                block_end = min(block_start + sub_block_size, n)
                # Use cutoff at block midpoint for this sub-block
                mid_idx = (block_start + block_end) // 2
                block_cutoff = float(cutoff_ramp[mid_idx])
                layer_filter.base_cutoff = block_cutoff
                layer_filter._build_filter(block_cutoff)
        
        # Volume — apply gain ramp directly to layer
        if "volume_db" in layer_ramps:
            # Convert dB ramp to linear gain ramp
            gain_ramp = 10.0 ** (layer_ramps["volume_db"] / 20.0)
            # Store as attribute for layer to use during synthesis
            # Note: This won't affect current chunk since layer already rendered,
            # but sets initial value for next chunk. For true intra-chunk volume,
            # we'd need to modify layer synthesis or apply post-synthesis.
            layer._gain = np.float32(gain_ramp[-1])
        
        # FM index — apply ramp directly to FM layer
        if "fm_index" in layer_ramps:
            if hasattr(layer, "fm_indices"):
                # Set to final value (layers don't support intra-chunk FM yet)
                layer.fm_indices[:] = np.float32(layer_ramps["fm_index"][-1])
        
        # Width — apply ramp to panner
        if "width" in layer_ramps:
            # Set to final value (panner doesn't support intra-chunk yet)
            panner.width = float(layer_ramps["width"][-1])
        
        # Non-interpolated parameters (apply once)
        if "distortion_drive" in layer_ramps:
            distortion.drive = float(layer_ramps["distortion_drive"])
        if "chorus_rate" in layer_ramps:
            self.choruses[i].rate = float(layer_ramps["chorus_rate"])
        if "lfo_rate" in layer_ramps:
            layer_filter.lfo_rate = float(layer_ramps["lfo_rate"])
        if "detune_cents" in layer_ramps:
            if hasattr(layer, "set_detune_cents"):
                layer.set_detune_cents(float(layer_ramps["detune_cents"]))
        if "granular_position" in layer_ramps:
            from .granular_layer import StreamingGranularLayer
            if isinstance(layer, StreamingGranularLayer):
                layer.position = float(layer_ramps["granular_position"])

    def _apply_automation(self, t_norm: float) -> None:
        """Inject automated parameter values for this chunk's time position."""
        # Per-layer automations
        for i, auto in enumerate(self._layer_automations):
            if not auto:
                continue

            if "filter_cutoff" in auto:
                v = auto["filter_cutoff"].value_at(t_norm)
                flt = self.filters[i]
                flt.base_cutoff = v
                if flt.filter_type not in ("off", "comb", "formant"):
                    flt._build_filter(v)

            if "fm_index" in auto:
                v = auto["fm_index"].value_at(t_norm)
                layer = self.layers[i]
                if hasattr(layer, "fm_indices"):
                    layer.fm_indices[:] = np.float32(v)

            if "distortion_drive" in auto:
                self.distortions[i].drive = auto["distortion_drive"].value_at(t_norm)

            if "volume_db" in auto:
                v = auto["volume_db"].value_at(t_norm)
                self.layers[i]._gain = np.float32(10.0 ** (v / 20.0))

            if "width" in auto:
                self.panners[i].width = auto["width"].value_at(t_norm)

            if "chorus_rate" in auto:
                self.choruses[i].rate = float(auto["chorus_rate"].value_at(t_norm))

            if "lfo_rate" in auto:
                self.filters[i].lfo_rate = float(auto["lfo_rate"].value_at(t_norm))

            if "detune_cents" in auto:
                layer = self.layers[i]
                if hasattr(layer, "set_detune_cents"):
                    layer.set_detune_cents(float(auto["detune_cents"].value_at(t_norm)))

            if "granular_position" in auto:
                from .granular_layer import StreamingGranularLayer
                layer = self.layers[i]
                if isinstance(layer, StreamingGranularLayer):
                    layer.position = float(auto["granular_position"].value_at(t_norm))

        # Global automations
        g = self._global_automations
        if not g:
            return

        if "reverb_mix" in g:
            self._reverb.mix = g["reverb_mix"].value_at(t_norm)

        if "reverb_decay_trim" in g:
            trim = g["reverb_decay_trim"].value_at(t_norm)
            self._reverb.decay = 0.60 + float(np.clip(trim, 0.0, 1.0)) * 0.36

        if "shimmer_wet" in g:
            self._shimmer.wet = g["shimmer_wet"].value_at(t_norm)

        if "binaural_beat_hz" in g:
            self._binaural_cfg["beat_hz"] = g["binaural_beat_hz"].value_at(t_norm)

        if "master_air_db" in g:
            self._master.set_air_db(g["master_air_db"].value_at(t_norm))

        if "master_output_db" in g:
            self._master.set_output_gain_db(g["master_output_db"].value_at(t_norm))

        if "saturation" in g:
            self.saturation = float(np.clip(g["saturation"].value_at(t_norm), 0.0, 1.0))

    def reload(self, new_preset: dict, crossfade_secs: float = 3.0) -> None:
        """
        Queue a hot-reload to the new preset with a smooth crossfade.
        Applied atomically at the start of the next chunk (avoids race condition
        between _build_from_preset on the event loop and next_chunk in a thread).
        If called multiple times before the next chunk fires, only the latest wins.
        """
        self._pending_reload = (new_preset, crossfade_secs)

    def get_peak_meters(self) -> list:
        """Return per-layer peak levels in dBFS with smooth decay (-100 = silent, 0 = full)."""
        return list(self._peak_meters)

    def _apply_binaural(self, stereo: np.ndarray, n: int) -> None:
        """
        Apply binaural entrainment in-place as the final stage of the chain.

        carrier mode: adds independent L/R sine tones (carrier ± beat_hz/2),
                      producing a true binaural beat on headphones.

        detune mode:  applies synchronized tremolo (amplitude modulation) to both
                      channels at beat_hz, creating a gentle pulsing/breathing
                      sensation. Stays centered in stereo field.
        """
        binaural = self._binaural_cfg
        if not binaural or not binaural.get("enabled", False):
            return
        beat_hz = float(binaural.get("beat_hz", 6.0))
        method  = binaural.get("method", "detune")
        t = (self._binaural_t + np.arange(n)) / self.SR
        self._binaural_t += n

        if method == "carrier":
            carrier_hz  = float(binaural.get("carrier_hz", 200.0))
            carrier_amp = float(binaural.get("carrier_amplitude", 0.15))
            freq_l = carrier_hz - beat_hz / 2.0
            freq_r = carrier_hz + beat_hz / 2.0
            stereo[:, 0] += (np.sin(2 * np.pi * freq_l * t) * carrier_amp).astype(np.float32)
            stereo[:, 1] += (np.sin(2 * np.pi * freq_r * t) * carrier_amp).astype(np.float32)
        else:  # detune
            # Gentle tremolo: oscillates 0.7 → 1.0 → 0.7 at beat_hz
            # Shallow depth (0.3) creates subtle pulse without aggressive pumping
            theta = (2 * np.pi * beat_hz * t).astype(np.float32)
            tremolo = 0.85 + 0.15 * np.cos(theta)  # 0.7 → 1.0 → 0.7
            stereo[:, 0] *= tremolo
            stereo[:, 1] *= tremolo

    def _earth_chunk(self, n: int) -> np.ndarray:
        cfg = self.earth_cfg
        dt = 1.0 / self.SR
        freq = float(cfg.get("tectonic_frequency", 18))
        pressure = float(cfg.get("pressure", 0.4))
        movement = float(cfg.get("movement", 0.02))

        t = np.arange(n) * dt

        # Wobble
        wobble_inc = 2 * np.pi * movement * t
        wobble_phases = self.earth_wobble_phase + np.cumsum(wobble_inc * dt * self.SR)
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

        # R2: Stereo decorrelation via small phase offset
        # Create slight L/R difference without losing low-freq coherence
        # Use a shallow allpass-like delay (3-5 samples on one channel)
        delay_samps = 4  # ~0.1ms @ 44.1kHz, ~0.08ms @ 48kHz
        signal_R = np.concatenate([self._earth_delay_buf, signal[:-delay_samps]])
        self._earth_delay_buf = signal[-delay_samps:].copy()
        
        stereo = np.stack([signal * 0.5, signal_R * 0.5], axis=1)
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
        state = self._air_state
        for i in range(n):
            state = alpha * noise[i] + (1 - alpha) * state
            smoothed[i] = state
        self._air_state = np.float32(state)

        signal = smoothed * intensity
        stereo = np.stack([signal * 0.5, signal * 0.5], axis=1)
        return stereo


class _ShallowCopy:
    """
    Wraps an engine's current state for crossfade.
    Captures the layers/panners so the old sound continues briefly.
    """

    def __init__(self, engine: StreamingDroneEngine):
        # MANT-1: Copy sample rate
        self.SR = engine.SR
        self.render_mode = engine.render_mode
        self.layers  = engine.layers
        self.panners = engine.panners
        self.choruses = engine.choruses
        self.filters = engine.filters
        self.distortions = engine.distortions
        self.flangers = engine.flangers
        self.phasers  = engine.phasers
        self.earth_cfg = engine.earth_cfg
        self.air_cfg   = engine.air_cfg
        self.earth_phase = engine.earth_phase
        self.earth_wobble_phase = engine.earth_wobble_phase
        self._earth_delay_buf = engine._earth_delay_buf.copy()  # R2: Copy delay buffer
        self._air_kernel = engine._air_kernel
        self._air_state  = engine._air_state
        self._dc_sos  = engine._dc_sos
        self._dc_zi_L = engine._dc_zi_L.copy()
        self._dc_zi_R = engine._dc_zi_R.copy()
        self.saturation = engine.saturation
        self._limiter_gain = engine._limiter_gain
        self._master = engine._master.copy_state()
        self._reverb  = engine._reverb.copy_state()
        self._shimmer = engine._shimmer.copy_state()
        self._binaural_cfg = engine._binaural_cfg
        self._binaural_t   = engine._binaural_t
        self._crossfade_remaining = 0
        self._crossfade_total = 0
        self._old_engine = None
        # MANT-9: copy automation state for crossfade continuity
        self._prev_layer_auto = dict(engine._prev_layer_auto)
        self._prev_global_auto = dict(engine._prev_global_auto)

    def next_chunk(self, n: int) -> np.ndarray:
        stereo = np.zeros((n, 2), dtype=np.float32)
        for layer, panner, chorus, layer_filter, distortion, flanger, phaser in zip(
            self.layers, self.panners, self.choruses, self.filters,
            self.distortions, self.flangers, self.phasers
        ):
            raw       = layer.next_chunk(n)
            filtered  = layer_filter.next_chunk(raw)
            distorted = distortion.process(filtered)
            panned    = panner.process(distorted)
            chorused  = chorus.next_chunk(panned)
            flanged   = flanger.next_chunk(chorused)
            phased    = phaser.next_chunk(flanged)
            stereo   += phased

        stereo[:, 0], self._dc_zi_L = sosfilt(self._dc_sos, stereo[:, 0], zi=self._dc_zi_L)
        stereo[:, 1], self._dc_zi_R = sosfilt(self._dc_sos, stereo[:, 1], zi=self._dc_zi_R)

        if self.saturation > 0.01:
            drive = 1.0 + self.saturation * 3.0
            norm = np.tanh(drive)
            
            # R3: Use oversampling for global saturation (2× for memory efficiency)
            # Apply global saturation (oversampling removed - caused clicks at chunk boundaries)
            stereo = np.tanh(stereo * drive) / norm

        stereo = self._reverb.next_chunk(stereo)
        stereo = self._shimmer.next_chunk(stereo)

        stereo = self._master.process(stereo)

        peak = float(np.max(np.abs(stereo)))
        target = min(1.0, 0.92 / peak) if peak > 1e-6 else 1.0
        gain_ramp = np.linspace(self._limiter_gain, target, stereo.shape[0], dtype=np.float64)
        stereo = stereo * gain_ramp[:, np.newaxis]
        self._limiter_gain = target

        return stereo
