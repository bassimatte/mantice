"""
engine/drone_engine.py — MANTICE V10.0
------------------------------------
Core audio engine.

Features:
  - Per-layer stereo panning (quadrant + trajectory)
  - SubharmonicEarth and AirPressureEngine in the build pipeline
  - Per-layer raised-cosine envelope
  - sosfilt-based filters (via filters.py)
  - Per-voice variable drift rate (via fm_voice.py)
  - Binaural beats (detune or carrier mode)
  - Central config.SAMPLE_RATE from config.py
"""

import random

import numpy as np

from . import config as _cfg
from .config              import FADE_SECS
from .filters             import Filters
from .fm_voice            import GentleFMVoice
from .spatial             import pan_layer, add_depth
from .binaural            import apply_binaural_detune, generate_binaural_carrier
from .subharmonic_earth   import SubharmonicEarth
from .air_pressure_engine import AirPressureEngine
from .convolution_reverb  import apply_convolution_reverb
from .master_processing   import apply_master_offline


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
            return stereo_layer
        else:
            if band == "sub":
                layer = Filters.lowpass(layer, 140)
            elif band == "mid":
                layer = Filters.bandpass(layer, 140, 1500)
            elif band == "high":
                layer = Filters.bandpass(layer, 1500, 7000)
            _apply_layer_filter()
            return layer


# ── Engine ────────────────────────────────────────────────────────────────────

class DroneEngine:

    def __init__(self, preset: dict):
        self.preset = preset

    def normalize(self, audio: np.ndarray, target: float = 0.92) -> np.ndarray:
        peak = np.max(np.abs(audio))
        if peak < 1e-9:
            return audio
        return audio / peak * target

    def build(self, progress_callback=None) -> np.ndarray:
        """
        Build the full stereo drone audio.
        progress_callback: optional callable, called with (1) after each stage completes.
        """
        cfg      = self.preset
        duration = cfg["duration"]
        samples  = int(duration * _cfg.SAMPLE_RATE)

        def _step():
            if progress_callback:
                progress_callback(1)

        # ── 1. Build each layer as mono, then pan to stereo ───────────────────
        stereo_mix = np.zeros((samples, 2))

        binaural_cfg = cfg.get("binaural")
        binaural_active = binaural_cfg and binaural_cfg.get("enabled", False)
        binaural_method = binaural_cfg.get("method", "detune") if binaural_active else None

        for layer_cfg in cfg["layers"]:
            if not layer_cfg["enabled"]:
                continue

            layer_result = DroneLayer(
                layer_cfg, duration,
                binaural_cfg=binaural_cfg if (binaural_active and binaural_method == "detune") else None
            ).build()

            if layer_result.ndim == 2:
                # Already stereo from binaural detune — apply mix level directly
                stereo_mix += layer_result * layer_cfg["mix"]
            else:
                mono = layer_result * layer_cfg["mix"]
                stereo_layer = pan_layer(
                    mono         = mono,
                    quadrant     = layer_cfg["quadrant"],
                    trajectory_x = layer_cfg["trajectory_x"],
                    trajectory_y = layer_cfg["trajectory_y"],
                    speed        = layer_cfg["speed"],
                )
                stereo_mix += stereo_layer
            _step()

        # ── 1b. Binaural carrier (if method == "carrier") ─────────────────────
        if binaural_active and binaural_method == "carrier":
            beat_hz = float(binaural_cfg.get("beat_hz", 6.0))
            carrier_hz = float(binaural_cfg.get("carrier_hz", 200.0))
            carrier_amp = float(binaural_cfg.get("carrier_amplitude", 0.15))
            carrier_signal = generate_binaural_carrier(
                carrier_hz=carrier_hz,
                beat_hz=beat_hz,
                amplitude=carrier_amp,
                duration=duration,
            )
            stereo_mix += carrier_signal
            _step()

        # ── 2. SubharmonicEarth ──────────────────────────────────────────────
        earth_cfg = cfg.get("earth")
        if earth_cfg and earth_cfg.get("enabled", True):
            earth_mono = SubharmonicEarth.generate(
                duration           = duration,
                tectonic_frequency = float(earth_cfg.get("tectonic_frequency", 18)),
                pressure           = float(earth_cfg.get("pressure", 0.4)),
                movement           = float(earth_cfg.get("movement", 0.02)),
            )
            earth_stereo = pan_layer(
                mono         = earth_mono,
                quadrant     = "center",
                trajectory_x = "drift",
                trajectory_y = "depth",
                speed        = 0.005,
            )
            stereo_mix += earth_stereo
            _step()

        # ── 3. AirPressureEngine ─────────────────────────────────────────────
        air_cfg = cfg.get("air")
        if air_cfg and air_cfg.get("enabled", True):
            air_mono = AirPressureEngine.generate(
                duration   = duration,
                intensity  = float(air_cfg.get("intensity",  0.12)),
                movement   = float(air_cfg.get("movement",   0.01)),
                turbulence = float(air_cfg.get("turbulence", 0.04)),
            )
            air_stereo = pan_layer(
                mono         = air_mono,
                quadrant     = "center",
                trajectory_x = "drift",
                trajectory_y = "none",
                speed        = 0.003,
            )
            stereo_mix += air_stereo
            _step()

        # ── 4. Global DC block ────────────────────────────────────────────────
        stereo_mix[:, 0] = Filters.highpass(stereo_mix[:, 0], 18)
        stereo_mix[:, 1] = Filters.highpass(stereo_mix[:, 1], 18)
        _step()

        # ── 5. Convolution Reverb ────────────────────────────────────────────
        reverb_cfg = cfg.get("reverb")
        if reverb_cfg and reverb_cfg.get("enabled", False):
            stereo_mix = apply_convolution_reverb(
                stereo_mix,
                space=reverb_cfg.get("space", "cathedral"),
                mix=float(reverb_cfg.get("mix", 0.3)),
                decay_trim=float(reverb_cfg.get("decay_trim", 1.0)),
            )
            _step()
        else:
            # Fallback: lightweight depth wash
            stereo_mix = add_depth(
                stereo_mix,
                depth=cfg["spatial_depth"],
                wet=cfg["spatial_wet"],
            )

        # ── 6. Global safety fade (short — layers have their own envelopes) ───
        fade_n = min(int(FADE_SECS * _cfg.SAMPLE_RATE), samples // 6)
        env    = np.ones(samples)
        env[:fade_n]  = np.linspace(0, 1, fade_n)
        env[-fade_n:] = np.linspace(1, 0, fade_n)
        stereo_mix   *= env[:, None]

        # ── 7. Normalise ──────────────────────────────────────────────────────
        result = self.normalize(stereo_mix)
        master_cfg = self.preset.get("master", {})
        result = apply_master_offline(result, _cfg.SAMPLE_RATE, master_cfg)
        _step()

        return result
