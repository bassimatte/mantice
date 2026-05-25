"""
engine/drone_engine.py
----------------------
Legacy offline drone engine — delegates to StreamingDroneEngine for correct
signal chain (DC → Saturation → FDN Reverb → Shimmer → Earth+Air → Master →
Limiter → Binaural). DroneLayer is kept for reference only.
"""

import random

import numpy as np

from . import config as _cfg
from .filters             import Filters
from .fm_voice            import GentleFMVoice
from .spatial             import pan_layer
from .binaural            import apply_binaural_detune, generate_binaural_carrier
from .subharmonic_earth   import SubharmonicEarth
from .air_pressure_engine import AirPressureEngine


# ── Layer ─────────────────────────────────────────────────────────────────────

class DroneLayer:

    def __init__(self, cfg: dict, duration: float, binaural_cfg: dict = None):
        self.cfg      = cfg
        self.duration = duration
        self.binaural = binaural_cfg

    def build(self) -> np.ndarray:
        """Build layer. Returns mono (N,) or stereo (N,2) if binaural detune is active."""
        cfg     = self.cfg
        samples = int(self.duration * _cfg.SAMPLE_RATE)

        binaural_detune = (
            self.binaural
            and self.binaural.get("enabled", False)
            and self.binaural.get("method", "detune") == "detune"
        )
        beat_hz = float(self.binaural.get("beat_hz", 6.0)) if binaural_detune else 0.0

        # Stagger attack/release slightly per layer for organic layering
        attack_secs  = random.uniform(2.5, 7.0)
        release_secs = random.uniform(4.0, 10.0)
        layer_type = cfg.get("type", "fm")

        if binaural_detune:
            stereo_layer = np.zeros((samples, 2))
        else:
            layer = np.zeros(samples)

        if layer_type == "subtractive":
            waveform = cfg.get("waveform", "saw")
            root = float(cfg["root"])
            detune_cents = float(cfg.get("detune_cents", 8.0))
            sub_mix = float(cfg.get("sub_mix", 0.3))
            n_voices = max(1, int(cfg.get("voices", 2)))
            ratios = cfg.get("ratios", [1.0])
            drift_amount = float(cfg.get("drift", 0.002))
            t = np.arange(samples) / _cfg.SAMPLE_RATE
            mono_layer = np.zeros(samples)
            voice_amps = []

            def _sub_wave(phases: np.ndarray) -> np.ndarray:
                phase_cycles = (phases / (2 * np.pi)) % 1.0
                if waveform == "square":
                    return np.where(np.sin(phases) >= 0.0, 1.0, -1.0)
                if waveform == "triangle":
                    return 2 * np.abs(2 * phase_cycles - 1) - 1
                return 2 * phase_cycles - 1

            for _ in range(n_voices):
                ratio = random.choice(ratios)
                f1 = root * ratio * (2 ** (detune_cents / 1200))
                f2 = root * ratio * (2 ** (-detune_cents / 1200))
                amp = random.uniform(cfg["amp_min"], cfg["amp_max"])
                phase1 = random.uniform(0, 2 * np.pi)
                phase2 = random.uniform(0, 2 * np.pi)
                drift_rate = random.uniform(0.001, 0.006)
                drift_phase = random.uniform(0, 2 * np.pi)
                drift_mod = 1.0 + np.sin(2 * np.pi * drift_rate * t + drift_phase) * drift_amount
                osc1_phase = phase1 + 2 * np.pi * np.cumsum(f1 * drift_mod / _cfg.SAMPLE_RATE)
                osc2_phase = phase2 + 2 * np.pi * np.cumsum(f2 * drift_mod / _cfg.SAMPLE_RATE)
                mono_layer += (_sub_wave(osc1_phase) + _sub_wave(osc2_phase)) * 0.5 * amp
                voice_amps.append(amp)

            sub_phase = random.uniform(0, 2 * np.pi)
            sub = np.sin(2 * np.pi * (root * 0.5) * t + sub_phase) * (np.mean(voice_amps) if voice_amps else 0.0)
            mono_layer = mono_layer * (1.0 - sub_mix) + sub * sub_mix

            if binaural_detune:
                stereo_layer = apply_binaural_detune(mono_layer, root, beat_hz, self.duration)
            else:
                layer = mono_layer
        else:
            for _ in range(cfg["voices"]):
                ratio     = random.choice(cfg["ratios"])
                fm_ratio  = random.choice(cfg["fm_ratios"])

                voice = GentleFMVoice(
                    carrier_freq = cfg["root"] * ratio,
                    mod_ratio    = fm_ratio,
                    fm_index     = cfg["fm_index"],
                    amplitude    = random.uniform(cfg["amp_min"], cfg["amp_max"]),
                    duration     = self.duration,
                    drift        = cfg["drift"],
                    drift_rate   = random.uniform(0.001, 0.006),
                    attack_secs  = attack_secs,
                    release_secs = release_secs,
                )
                mono_voice = voice.generate()

                if binaural_detune:
                    stereo_voice = apply_binaural_detune(
                        mono_voice, cfg["root"] * ratio, beat_hz, self.duration
                    )
                    stereo_layer += stereo_voice
                else:
                    layer += mono_voice

        def _apply_layer_filter() -> None:
            filter_type = cfg.get("filter_type", "off")
            if filter_type == "off":
                return
            from scipy.signal import butter, sosfilt
            cutoff = float(cfg.get("filter_cutoff", 2000))
            nyq = _cfg.SAMPLE_RATE * 0.5
            fc = float(np.clip(cutoff, 20.0, nyq * 0.99))
            try:
                if filter_type == "lp":
                    sos = butter(2, fc / nyq, btype="low", output="sos")
                elif filter_type == "hp":
                    sos = butter(2, fc / nyq, btype="high", output="sos")
                elif filter_type == "bp":
                    lo = np.clip(fc * 0.7, 20, nyq * 0.98)
                    hi = np.clip(fc * 1.4, lo + 10, nyq * 0.99)
                    sos = butter(2, [lo / nyq, hi / nyq], btype="band", output="sos")
                else:
                    sos = None
                if sos is not None:
                    if binaural_detune:
                        stereo_layer[:, 0] = sosfilt(sos, stereo_layer[:, 0])
                        stereo_layer[:, 1] = sosfilt(sos, stereo_layer[:, 1])
                    else:
                        nonlocal layer
                        layer = sosfilt(sos, layer)
            except Exception:
                pass

        # --- Distortion -----------------------------------------------------------
        def _apply_distortion(audio: np.ndarray) -> np.ndarray:
            drive = float(cfg.get("distortion_drive", 0.0))
            if drive < 0.01:
                return audio
            d = 1.0 + drive * 4.0
            dist_type = cfg.get("distortion_type", "soft")
            if dist_type == "hard":
                return np.clip(audio * d, -1.0, 1.0) / d
            return np.tanh(audio * d) / np.tanh(d)

        # --- Spectral band placement -------------------------------------------
        band = cfg.get("band", "mid")
        if binaural_detune:
            if band == "sub":
                stereo_layer[:, 0] = Filters.lowpass(stereo_layer[:, 0], 140)
                stereo_layer[:, 1] = Filters.lowpass(stereo_layer[:, 1], 140)
            elif band == "mid":
                stereo_layer[:, 0] = Filters.bandpass(stereo_layer[:, 0], 140, 1500)
                stereo_layer[:, 1] = Filters.bandpass(stereo_layer[:, 1], 140, 1500)
            elif band == "high":
                stereo_layer[:, 0] = Filters.bandpass(stereo_layer[:, 0], 1500, 7000)
                stereo_layer[:, 1] = Filters.bandpass(stereo_layer[:, 1], 1500, 7000)
            _apply_layer_filter()
            if binaural_detune:
                stereo_layer[:, 0] = _apply_distortion(stereo_layer[:, 0])
                stereo_layer[:, 1] = _apply_distortion(stereo_layer[:, 1])
            return stereo_layer
        else:
            if band == "sub":
                layer = Filters.lowpass(layer, 140)
            elif band == "mid":
                layer = Filters.bandpass(layer, 140, 1500)
            elif band == "high":
                layer = Filters.bandpass(layer, 1500, 7000)
            _apply_layer_filter()
            return _apply_distortion(layer)


# ── Engine ────────────────────────────────────────────────────────────────────

class DroneEngine:
    """
    Offline drone engine. Delegates to StreamingDroneEngine so that export
    output is bit-identical to the real-time web preview.

    The DroneLayer class above is kept for reference but is no longer called
    by build(). Use StreamingDroneEngine directly for new code.
    """

    def __init__(self, preset: dict):
        self.preset = preset

    def normalize(self, audio: np.ndarray, target: float = 0.92) -> np.ndarray:
        peak = np.max(np.abs(audio))
        if peak < 1e-9:
            return audio
        return audio / peak * target

    def build(self, progress_callback=None) -> np.ndarray:
        """
        Build full stereo drone audio by running the StreamingDroneEngine in
        chunks — identical signal chain to the real-time web preview.

        progress_callback is accepted for compatibility but not called per-step.
        """
        from .streaming_engine import StreamingDroneEngine

        seed = self.preset.get("seed") if self.preset.get("seed") is not None else 42
        engine = StreamingDroneEngine(self.preset, seed=int(seed))

        sr            = _cfg.SAMPLE_RATE
        total_samples = int(self.preset["duration"] * sr)
        chunk_size    = 2048
        chunks        = []
        remaining     = total_samples

        while remaining > 0:
            n = min(chunk_size, remaining)
            chunks.append(engine.next_chunk(n))
            remaining -= n

        audio = np.concatenate(chunks, axis=0)
        if progress_callback:
            progress_callback(1)
        return audio
