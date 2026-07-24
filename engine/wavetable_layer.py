"""Streaming wavetable oscillator for imported multi-frame WAV files."""

from pathlib import Path

import numpy as np
import soundfile as sf


def _resolve_wavetable_path(source: str, samples_dir: str) -> Path:
    """Resolve bundled/cache tables and immutable repository-backed tables."""
    samples_root = Path(samples_dir).resolve()
    if source.startswith("shared/wavetables/"):
        relative = Path(source)
        if len(relative.parts) != 3:
            raise ValueError("Wavetable source is missing or invalid")
        shared_root = (samples_root.parent / "shared" / "wavetables").resolve()
        path = (samples_root.parent / relative).resolve()
        if path.parent != shared_root or not path.is_file():
            raise ValueError(f"Wavetable not found: {source}")
        return path

    path = (samples_root / source).resolve()
    if samples_root not in path.parents or not path.is_file():
        raise ValueError(f"Wavetable not found: {source}")
    return path


def wavetable_scan_curve(mode: str, phase: np.ndarray) -> np.ndarray:
    """Shape normalized scan phase while preserving legacy mode names."""
    wrapped = np.asarray(phase) % 1.0
    if mode == "reverse":
        return 1.0 - wrapped
    if mode == "pingpong":
        return 1.0 - np.abs(2.0 * wrapped - 1.0)
    if mode == "sine":
        return 0.5 - 0.5 * np.cos(2.0 * np.pi * wrapped)
    return wrapped


def wavetable_random_unit(seed: int, target_index: int) -> float:
    """Return a stable pseudo-random value in [0, 1] without mutable RNG state."""
    value = (int(seed) + int(target_index) * 0x9E3779B9) & 0xFFFFFFFF
    value ^= value >> 16
    value = (value * 0x7FEB352D) & 0xFFFFFFFF
    value ^= value >> 15
    value = (value * 0x846CA68B) & 0xFFFFFFFF
    value ^= value >> 16
    return value / 0xFFFFFFFF


def _wavetable_random_units(seed: int, target_indices: np.ndarray) -> np.ndarray:
    """Vectorized counterpart to wavetable_random_unit for audio-rate rendering."""
    mask = np.uint64(0xFFFFFFFF)
    values = (np.uint64(int(seed) & 0xFFFFFFFF) + target_indices.astype(np.uint64) * np.uint64(0x9E3779B9)) & mask
    values ^= values >> np.uint64(16)
    values = (values * np.uint64(0x7FEB352D)) & mask
    values ^= values >> np.uint64(15)
    values = (values * np.uint64(0x846CA68B)) & mask
    values ^= values >> np.uint64(16)
    return values.astype(np.float64) / 0xFFFFFFFF


def wavetable_smooth_random_curve(phase: np.ndarray, seed: int) -> np.ndarray:
    """Cosine-interpolate deterministic random targets for each whole scan cycle."""
    absolute = np.asarray(phase, dtype=np.float64)
    segments = np.floor(absolute).astype(np.int64)
    fractions = absolute - segments
    eased = 0.5 - 0.5 * np.cos(np.pi * fractions)
    starts = _wavetable_random_units(seed, segments)
    ends = _wavetable_random_units(seed, segments + 1)
    return (starts + (ends - starts) * eased).astype(np.float32)


class StreamingWavetableLayer:
    """Polyphonic wavetable layer with smooth phase and frame interpolation."""

    def __init__(self, cfg: dict, samples_dir: str, sample_rate: int, scan_seed: int = 42):
        self.SR = int(sample_rate)
        self.cfg = cfg
        self.frame_size = max(32, int(cfg.get("wavetable_frame_size", 2048)))
        source = str(cfg.get("wavetable_source") or "")
        if not source or ".." in source:
            raise ValueError("Wavetable source is missing or invalid")
        path = _resolve_wavetable_path(source, samples_dir)

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

        # Wavetable unison is built in stereo before the layer panner.  The
        # previous engine summed randomly phased, randomly weighted voices to
        # mono, producing unstable combing without genuine stereo spread.
        self.unison_mode = str(cfg.get("wavetable_unison_mode", "synthetic")).lower()
        if self.unison_mode not in {"hard", "smooth", "synthetic"}:
            self.unison_mode = "synthetic"
        phase_rng = np.random.default_rng((int(scan_seed) ^ 0x51F15EED) & 0xFFFFFFFF)
        common_phase = np.float32(phase_rng.random())
        if self.unison_mode == "hard" or voices == 1 or detune <= 1e-6:
            self.phases = np.full(voices, common_phase, dtype=np.float32)
        elif self.unison_mode == "smooth":
            self.phases = phase_rng.random(voices).astype(np.float32)
        else:
            self.phases = (common_phase + np.arange(voices, dtype=np.float32) / voices) % 1.0

        amp_min = float(cfg.get("amp_min", 0.01))
        amp_max = float(cfg.get("amp_max", 0.05))
        base_amplitude = max(0.0, (amp_min + amp_max) * 0.5)
        spread = float(np.clip(cfg.get("wavetable_unison_spread", 0.8), 0.0, 1.0))
        blend = float(np.clip(cfg.get("wavetable_unison_blend", 0.75), 0.0, 1.0))
        normalized_voice_positions = (
            np.linspace(-1.0, 1.0, voices, dtype=np.float32)
            if voices > 1 else np.zeros(1, dtype=np.float32)
        )
        blend_weights = 1.0 - (1.0 - blend) * np.abs(normalized_voice_positions)
        # Preserve the approximate power of the legacy three-voice default,
        # while keeping perceived energy stable as Voice Count changes.
        weight_energy = max(1e-8, float(np.sqrt(np.sum(blend_weights ** 2))))
        self.amplitudes = (
            blend_weights * (base_amplitude * np.sqrt(3.0) / weight_energy)
        ).astype(np.float32)
        pan_positions = 0.5 + normalized_voice_positions * (0.5 * spread)
        pan_angles = pan_positions * np.float32(np.pi / 2.0)
        self._voice_left_gains = (self.amplitudes * np.cos(pan_angles)).astype(np.float32)
        self._voice_right_gains = (self.amplitudes * np.sin(pan_angles)).astype(np.float32)
        self._gain = np.float32(10.0 ** (float(cfg.get("volume_db", 0.0)) / 20.0))

        self.position = float(np.clip(cfg.get("wavetable_position", 0.0), 0.0, 1.0))
        self.scan_start = float(np.clip(cfg.get("wavetable_scan_start", 0.0), 0.0, 1.0))
        self.scan_end = float(np.clip(cfg.get("wavetable_scan_end", 1.0), 0.0, 1.0))
        if self.scan_end < self.scan_start:
            self.scan_start, self.scan_end = self.scan_end, self.scan_start
        self.scan_rate = max(0.0, float(cfg.get("wavetable_scan_rate", 0.01)))
        self.scan_mode = str(cfg.get("wavetable_scan_mode", "pingpong"))
        legacy_shapes = {
            "static": "static", "forward": "ramp", "reverse": "ramp",
            "pingpong": "triangle", "sine": "sine", "smooth_random": "smooth_random",
        }
        requested_shape = str(cfg.get("wavetable_scan_shape") or legacy_shapes.get(self.scan_mode, "triangle"))
        self.scan_shape = requested_shape if requested_shape in {"static", "ramp", "triangle", "sine", "smooth_random"} else "triangle"
        legacy_direction = "reverse" if self.scan_mode == "reverse" else "forward"
        requested_direction = str(cfg.get("wavetable_scan_direction") or legacy_direction)
        self.scan_direction = requested_direction if requested_direction in {"forward", "reverse"} else "forward"
        if self.scan_shape == "static":
            self.position = float(np.clip(self.position, self.scan_start, self.scan_end))
        self.scan_seed = int(scan_seed) & 0xFFFFFFFF
        self.scan_phase = 0.0
        self.tremor_amount = float(np.clip(cfg.get("wavetable_tremor_amount", 0.0), 0.0, max(0, frame_count - 1)))
        self.tremor_rate = max(0.0, float(cfg.get("wavetable_tremor_rate", 0.3)))
        self.tremor_seed = self.scan_seed ^ 0xA5A5A5A5
        self.tremor_phase = 0.0
        self.audio_rate_scan = bool(cfg.get("wavetable_audio_rate_scan", False)) or self.scan_rate > 20.0
        self._bandlimited_table_cache: dict[int, np.ndarray] = {}
        self._table_spectrum = None
        self._voice_harmonic_limits: list[int] = []
        self._voice_tables = []
        for frequency in self.freqs:
            harmonic_limit = self._harmonic_limit(float(frequency))
            self._voice_harmonic_limits.append(harmonic_limit)
            self._voice_tables.append(self._bandlimited_table(harmonic_limit))
        self._table_spectrum = None

    def _harmonic_limit(self, frequency: float) -> int:
        """Leave a Nyquist guard band for fast frame-position modulation."""
        highest_table_harmonic = max(1, self.frame_size // 2 - 1)
        scan_guard_hz = max(100.0, self.scan_rate * 2.0, self.tremor_rate * 2.0)
        safe_nyquist = max(frequency, self.SR * 0.5 - scan_guard_hz)
        safe_limit = max(1, min(highest_table_harmonic, int(safe_nyquist * 0.9 / frequency)))
        # Quantize downward into conservative mip-style buckets so nearby
        # detuned voices share one filtered table instead of duplicating memory.
        if safe_limit <= 16:
            step = 1
        elif safe_limit <= 32:
            step = 2
        elif safe_limit <= 64:
            step = 4
        elif safe_limit <= 128:
            step = 8
        elif safe_limit <= 256:
            step = 16
        else:
            step = 32
        return max(1, (safe_limit // step) * step)

    def _bandlimited_table(self, harmonic_limit: int) -> np.ndarray:
        """Build and cache a periodic FFT-filtered table for a voice frequency."""
        highest_table_harmonic = self.frame_size // 2 - 1
        if harmonic_limit >= highest_table_harmonic:
            return self.table
        cached = self._bandlimited_table_cache.get(harmonic_limit)
        if cached is not None:
            return cached
        if self._table_spectrum is None:
            self._table_spectrum = np.fft.rfft(self.table, axis=1)
        spectrum = self._table_spectrum.copy()
        spectrum[:, harmonic_limit + 1:] = 0.0
        filtered = np.fft.irfft(spectrum, n=self.frame_size, axis=1).astype(np.float32)
        self._bandlimited_table_cache[harmonic_limit] = filtered
        return filtered

    def _frame_positions(self, n_samples: int) -> np.ndarray:
        if self.frame_count == 1:
            return np.zeros(n_samples, dtype=np.float32)
        if self.scan_shape == "static" or self.scan_rate <= 0.0:
            frame_positions = np.full(n_samples, self.position * (self.frame_count - 1), dtype=np.float32)
        else:
            phase_step = self.scan_rate / self.SR
            running_phase = self.scan_phase + np.arange(n_samples, dtype=np.float64) * phase_step
            # Position selects the static frame or, while scanning, offsets
            # the scan phase so the same control always moves the playhead.
            phase = running_phase + self.position
            if self.scan_shape == "smooth_random":
                curve = wavetable_smooth_random_curve(phase, self.scan_seed)
                self.scan_phase = float(running_phase[-1] + phase_step)
            else:
                shape_mode = {"ramp": "forward", "triangle": "pingpong"}.get(self.scan_shape, self.scan_shape)
                curve = wavetable_scan_curve(shape_mode, phase)
                self.scan_phase = float((running_phase[-1] + phase_step) % 1.0)
            if self.scan_direction == "reverse":
                curve = 1.0 - curve
            normalized = self.scan_start + curve * (self.scan_end - self.scan_start)
            frame_positions = normalized * np.float32(self.frame_count - 1)

        if self.tremor_amount > 0.0 and self.tremor_rate > 0.0:
            tremor_phase = self.tremor_phase + np.arange(n_samples, dtype=np.float64) * (self.tremor_rate / self.SR)
            tremor = wavetable_smooth_random_curve(tremor_phase, self.tremor_seed) * 2.0 - 1.0
            self.tremor_phase = float(tremor_phase[-1] + self.tremor_rate / self.SR)
            frame_positions = frame_positions + tremor * np.float32(self.tremor_amount)
            low = self.scan_start * (self.frame_count - 1)
            high = self.scan_end * (self.frame_count - 1)
            frame_positions = np.clip(frame_positions, low, high)
        return np.asarray(frame_positions, dtype=np.float32)

    def next_chunk(self, n_samples: int) -> np.ndarray:
        frame_pos = self._frame_positions(n_samples)
        frame0 = np.floor(frame_pos).astype(np.int32)
        frame1 = np.minimum(frame0 + 1, self.frame_count - 1)
        frame_mix = frame_pos - frame0
        output_left = np.zeros(n_samples, dtype=np.float32)
        output_right = np.zeros(n_samples, dtype=np.float32)

        for voice, frequency in enumerate(self.freqs):
            voice_table = self._voice_tables[voice]
            phase = (self.phases[voice] + np.arange(n_samples, dtype=np.float32) * (frequency / self.SR)) % 1.0
            sample_pos = phase * self.frame_size
            sample0 = np.floor(sample_pos).astype(np.int32) % self.frame_size
            sample1 = (sample0 + 1) % self.frame_size
            sample_mix = sample_pos - np.floor(sample_pos)
            wave0 = voice_table[frame0, sample0] * (1.0 - sample_mix) + voice_table[frame0, sample1] * sample_mix
            wave1 = voice_table[frame1, sample0] * (1.0 - sample_mix) + voice_table[frame1, sample1] * sample_mix
            voice_output = wave0 * (1.0 - frame_mix) + wave1 * frame_mix
            output_left += voice_output * self._voice_left_gains[voice]
            output_right += voice_output * self._voice_right_gains[voice]
            self.phases[voice] = np.float32((phase[-1] + frequency / self.SR) % 1.0)

        return np.column_stack([output_left, output_right]) * self._gain
