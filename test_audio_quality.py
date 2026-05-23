#!/usr/bin/env python3
"""
test_audio_quality.py
---------------------
Audio quality regression test suite for Mantice.

Renders short clips of every configuration and detects:
  - Clicks / amplitude discontinuities (both intra-chunk and at chunk boundaries)
  - Clipping (peak > 0.98)
  - NaN / Inf (numerical instability)
  - Silence (rms < threshold)
  - DC offset

Usage:
    py -3 test_audio_quality.py                 # full suite (~300 tests, ~8 min)
    py -3 test_audio_quality.py --quick         # fast subset (~60 tests, ~2 min)
    py -3 test_audio_quality.py --section gran  # one section only
    py -3 test_audio_quality.py --save-flagged  # write failed renders to test_flagged/
    py -3 test_audio_quality.py --verbose       # print metrics for passing tests too

Sections: fm | sub | gran | fx | transition | presets
"""

import argparse
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import soundfile as sf

# ── Add repo root to sys.path ─────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from engine import config as eng_config
from engine.streaming_engine import StreamingDroneEngine

SR         = eng_config.STREAM_SAMPLE_RATE   # 22050 — engine's internal rate
SAMPLES_DIR = REPO_ROOT / "samples"
SHARED_DIR  = REPO_ROOT / "shared"
FLAGGED_DIR = REPO_ROOT / "test_flagged"

# ── Render parameters ─────────────────────────────────────────────────────────
# Must match the engine's internal default (StreamingDroneEngine.chunk_size = 2048)
# The FDN reverb buffer is sized at init time and crashes on mismatched chunks.
CHUNK_SIZE     = 2048
TEST_DURATION  = 6          # seconds per test render
RELOAD_DURATION = 8         # seconds for crossfade tests

# ── Detection thresholds ──────────────────────────────────────────────────────
CLICK_THRESHOLD        = 0.15   # |diff| between adjacent samples
CLICK_COUNT_FAIL       = 3      # fail if ≥ this many clicks
BOUNDARY_CLICK_FAIL    = 1      # fail if ≥ this many chunk-boundary clicks
CLIP_THRESHOLD         = 0.98   # |peak| above this → clipping
SILENCE_RMS            = 5e-5   # rms below this → silence
DC_THRESHOLD           = 0.05   # |mean| above this → DC offset
RMS_SPIKE_RATIO        = 4.0    # max/median windowed RMS above this → burst
SEAM_CLICK_THRESHOLD   = 0.10   # tighter threshold inside a crossfade seam


# ═════════════════════════════════════════════════════════════════════════════
# Preset builder helpers
# ═════════════════════════════════════════════════════════════════════════════

_LAYER_BASE = dict(
    name="Test",
    muted=False,
    quadrant="center",
    trajectory_x="none",
    trajectory_y="none",
    speed=0.01,
    pan=0.0,
    width=1.0,
    elevation=0.0,
    elevation_motion="static",
    elevation_speed=0.1,
    elevation_range=60.0,
    chorus_rate=0.5,
    chorus_depth=0.005,
    chorus_mix=0.0,
    chorus_voices=2,
    filter_type="off",
    filter_cutoff=2000.0,
    filter_resonance=1.0,
    filter_lfo_rate=0.1,
    filter_lfo_depth=0.0,
    filter_lfo_shape="sine",
    filter_vowel="a",
    distortion_drive=0.0,
    distortion_type="soft",
    # subtractive defaults
    waveform="saw",
    detune_cents=8.0,
    sub_mix=0.3,
    # noise / harmonics
    harmonics=4,
    harmonic_decay=0.7,
    noise_amount=0.0,
    noise_color="pink",
)

_PRESET_BASE = dict(
    seed=42,
    duration=60,
    spatial_depth=1.0,
    spatial_wet=0.3,
    swarm_density=0.5,
    saturation=0.2,
    binaural=None,
    reverb=None,
    earth=None,
    air=None,
    flanger=None,
    master={},
)


def _fm(**kw) -> dict:
    return {
        **_LAYER_BASE,
        "type": "fm",
        "root": 220.0,
        "voices": 4,
        "ratios": [1.0, 2.0],
        "fm_ratios": [1.0],
        "fm_index": 0.1,
        "amp_min": 0.005,
        "amp_max": 0.04,
        "drift": 0.01,
        "mix": 0.8,
        "band": "mid",
        **kw,
    }


def _sub(**kw) -> dict:
    return {
        **_LAYER_BASE,
        "type": "subtractive",
        "root": 220.0,
        "voices": 3,
        "ratios": [1.0],
        "fm_ratios": [1.0],
        "fm_index": 0.0,
        "amp_min": 0.005,
        "amp_max": 0.04,
        "drift": 0.01,
        "mix": 0.8,
        "band": "mid",
        **kw,
    }


def _gran(source="singing_bowl.ogg", **kw) -> dict:
    return {
        **_LAYER_BASE,
        "type": "granular",
        "root": 220.0,
        "source": source,
        "grain_size": 80.0,
        "density": 12.0,
        "pitch_spread": 0.3,
        "pitch_semitones": 0.0,
        "sample_root_hz": None,
        "pitch_mode": "resample",
        "position": 0.5,
        "scatter": 0.4,
        "envelope": "hann",
        "position_mode": "linear",
        "position_chaos": 0.3,
        "mix": 0.8,
        "voices": 1,
        "ratios": [1.0],
        "fm_ratios": [1.0],
        "fm_index": 0.0,
        "amp_min": 0.005,
        "amp_max": 0.04,
        "drift": 0.01,
        "band": "mid",
        **kw,
    }


def _preset(layers: list, **kw) -> dict:
    return {**_PRESET_BASE, "layers": layers, **kw}


# ═════════════════════════════════════════════════════════════════════════════
# Render helpers
# ═════════════════════════════════════════════════════════════════════════════

def render(preset: dict, duration: float = TEST_DURATION, seed: int = 42) -> np.ndarray:
    """Render preset for `duration` seconds. Returns (N,2) float32 stereo."""
    engine = StreamingDroneEngine(preset, seed=seed)
    total = int(duration * SR)
    chunks = []
    remaining = total
    while remaining > 0:
        n = min(CHUNK_SIZE, remaining)
        chunks.append(engine.next_chunk(n))
        remaining -= n
    return np.concatenate(chunks, axis=0)


def render_with_reload(
    preset_a: dict,
    preset_b: dict,
    duration: float = RELOAD_DURATION,
    crossfade: float = 2.0,
    seed: int = 42,
) -> np.ndarray:
    """Render preset_a, hot-reload to preset_b mid-way, return full audio."""
    engine = StreamingDroneEngine(preset_a, seed=seed)
    total = int(duration * SR)
    reload_at = total // 2
    chunks = []
    rendered = 0
    reloaded = False
    while rendered < total:
        if not reloaded and rendered >= reload_at:
            engine.reload(preset_b, crossfade_secs=crossfade)
            reloaded = True
        n = min(CHUNK_SIZE, total - rendered)
        chunks.append(engine.next_chunk(n))
        rendered += n
    return np.concatenate(chunks, axis=0)


def render_with_reload_seam(
    preset_a: dict,
    preset_b: dict,
    crossfade: float = 2.0,
    extra_before: float = 1.0,
    extra_after: float = 1.0,
    seed: int = 42,
) -> tuple[np.ndarray, int, float]:
    """Render a hot-reload and return (full_audio, reload_sample, crossfade_secs).

    Renders extra_before + crossfade + extra_after seconds so the seam is
    always centred and fully captured.
    """
    duration = extra_before + crossfade + extra_after
    reload_at = int(extra_before * SR)
    engine = StreamingDroneEngine(preset_a, seed=seed)
    total = int(duration * SR)
    chunks = []
    rendered = 0
    reloaded = False
    while rendered < total:
        if not reloaded and rendered >= reload_at:
            engine.reload(preset_b, crossfade_secs=crossfade)
            reloaded = True
        n = min(CHUNK_SIZE, total - rendered)
        chunks.append(engine.next_chunk(n))
        rendered += n
    return np.concatenate(chunks, axis=0), reload_at, crossfade


# ═════════════════════════════════════════════════════════════════════════════
# Audio analysis
# ═════════════════════════════════════════════════════════════════════════════

def analyze(audio: np.ndarray) -> dict:
    """Compute quality metrics from (N,2) stereo audio."""
    mono = audio.mean(axis=1) if audio.ndim == 2 else audio
    mono = mono.astype(np.float64)

    diff = np.abs(np.diff(mono))

    # Chunk-boundary analysis: check the seam between every pair of adjacent chunks
    n = len(mono)
    # Indices of last sample before each chunk boundary
    boundary_end   = np.arange(CHUNK_SIZE - 1, n - 1, CHUNK_SIZE)
    boundary_start = boundary_end + 1
    if len(boundary_start) > 0 and boundary_start[-1] < n:
        bdiff = np.abs(mono[boundary_end] - mono[boundary_start])
        boundary_clicks = int((bdiff > CLICK_THRESHOLD).sum())
        boundary_max    = float(bdiff.max())
    else:
        boundary_clicks = 0
        boundary_max    = 0.0

    return dict(
        click_count      = int((diff > CLICK_THRESHOLD).sum()),
        click_max        = float(diff.max()) if len(diff) else 0.0,
        boundary_clicks  = boundary_clicks,
        boundary_max     = round(boundary_max, 4),
        peak             = float(np.abs(mono).max()),
        rms              = float(np.sqrt(np.mean(mono ** 2))),
        dc               = float(abs(mono.mean())),
        has_nan          = bool(np.isnan(mono).any() or np.isinf(mono).any()),
        rms_spike        = _rms_spike_ratio(mono),
    )


def _rms_spike_ratio(mono: np.ndarray, window_ms: float = 500.0) -> float:
    """Max/median ratio across overlapping RMS windows. 1.0 = perfectly flat."""
    window = int(window_ms * SR / 1000)
    if len(mono) < window * 3:
        return 1.0
    hop = window // 2
    rms_vals = np.array([
        np.sqrt(np.mean(mono[i: i + window] ** 2))
        for i in range(0, len(mono) - window, hop)
    ])
    active = rms_vals[rms_vals > 1e-4]
    if len(active) < 3:
        return 1.0
    return float(active.max() / (np.median(active) + 1e-8))


def analyze_seam(audio: np.ndarray, reload_at: int, crossfade_secs: float,
                 extra_secs: float = 0.3) -> dict:
    """Analyze only the crossfade window ± extra_secs around the reload point."""
    extra = int(extra_secs * SR)
    window_end = int(reload_at + crossfade_secs * SR + extra)
    start = max(0, reload_at - extra)
    end   = min(len(audio), window_end)
    seam  = audio[start:end]
    m = analyze(seam)
    # Use tighter threshold for the seam window
    seam_clicks = int((np.abs(np.diff(
        seam.mean(axis=1) if seam.ndim == 2 else seam
    )) > SEAM_CLICK_THRESHOLD).sum())
    m["seam_clicks"] = seam_clicks
    return m


def render_seam_slice(
    preset_a: dict,
    preset_b: dict,
    crossfade: float = 2.0,
    extra: float = 0.5,
    seed: int = 42,
) -> np.ndarray:
    """Return only the crossfade window (extra + crossfade + extra seconds).

    Shorter than a full render, but scoped exactly around the transition seam
    so the standard click detector can evaluate it with tighter context.
    """
    audio, _reload_at, _cf = render_with_reload_seam(
        preset_a, preset_b, crossfade=crossfade,
        extra_before=extra, extra_after=extra, seed=seed,
    )
    return audio


def judge(m: dict) -> list[str]:
    """Return list of failure strings; empty list = pass."""
    issues = []
    if m["has_nan"]:
        issues.append("NaN/Inf in output")
    if m["click_count"] >= CLICK_COUNT_FAIL:
        issues.append(f"clicks={m['click_count']}  max_jump={m['click_max']:.3f}")
    if m["boundary_clicks"] >= BOUNDARY_CLICK_FAIL:
        issues.append(f"chunk-boundary clicks={m['boundary_clicks']}  max={m['boundary_max']:.3f}")
    if m["peak"] > CLIP_THRESHOLD:
        issues.append(f"clipping  peak={m['peak']:.4f}")
    if m["rms"] < SILENCE_RMS:
        issues.append(f"silence  rms={m['rms']:.2e}")
    if m["dc"] > DC_THRESHOLD:
        issues.append(f"DC offset={m['dc']:.4f}")
    if m.get("rms_spike", 1.0) > RMS_SPIKE_RATIO:
        issues.append(f"rms_burst  spike_ratio={m['rms_spike']:.1f}x")
    return issues


# ═════════════════════════════════════════════════════════════════════════════
# Test result
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class Result:
    section: str
    name: str
    desc: str
    passed: bool
    issues: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    error: Optional[str] = None
    audio: Optional[np.ndarray] = field(default=None, repr=False)
    elapsed: float = 0.0


def run_test(section: str, name: str, desc: str,
             fn: Callable[[], np.ndarray],
             keep_audio: bool = False) -> Result:
    t0 = time.time()
    try:
        audio = fn()
        metrics = analyze(audio)
        issues = judge(metrics)
        return Result(
            section=section, name=name, desc=desc,
            passed=len(issues) == 0,
            issues=issues, metrics=metrics,
            audio=audio if (not issues and not keep_audio) else (audio if keep_audio else None),
            elapsed=time.time() - t0,
        )
    except Exception:
        return Result(
            section=section, name=name, desc=desc,
            passed=False, issues=["EXCEPTION"],
            error=traceback.format_exc(),
            elapsed=time.time() - t0,
        )


# ═════════════════════════════════════════════════════════════════════════════
# Test suite definitions
# ═════════════════════════════════════════════════════════════════════════════

def suite_fm(quick: bool) -> list[tuple]:
    tests = []

    roots = [55, 110, 220, 440] if not quick else [110, 440]
    for r in roots:
        p = _preset([_fm(root=r)])
        tests.append((f"root_{r}Hz", f"FM root={r}Hz",
                       lambda _p=p: render(_p)))

    for v in ([1, 4, 8, 16] if not quick else [4]):
        p = _preset([_fm(voices=v)])
        tests.append((f"voices_{v}", f"FM voices={v}",
                       lambda _p=p: render(_p)))

    for idx in ([0.0, 0.05, 0.5, 2.0, 5.0] if not quick else [0.1, 2.0]):
        p = _preset([_fm(fm_index=idx)])
        tests.append((f"fm_index_{idx}", f"FM index={idx}",
                       lambda _p=p: render(_p)))

    # Bands
    for band in (["sub", "mid", "high"] if not quick else ["sub", "mid"]):
        p = _preset([_fm(band=band, root=110 if band == "sub" else 220)])
        tests.append((f"band_{band}", f"FM band={band}",
                       lambda _p=p: render(_p)))

    # Drift extremes
    for drift in ([0.0, 0.05, 0.1] if not quick else [0.05]):
        p = _preset([_fm(drift=drift)])
        tests.append((f"drift_{drift}", f"FM drift={drift}",
                       lambda _p=p: render(_p)))

    # Filter types
    for ftype in (["lp", "hp", "bp", "notch", "vowel", "off"] if not quick else ["lp", "off"]):
        p = _preset([_fm(filter_type=ftype,
                         filter_lfo_depth=0.5 if ftype != "off" else 0.0,
                         filter_lfo_rate=0.5)])
        tests.append((f"filter_{ftype}", f"FM filter={ftype}",
                       lambda _p=p: render(_p)))

    # Multi-layer
    for n_layers in ([2, 3, 5] if not quick else [3]):
        roots_ml = [55, 110, 220, 440, 880][:n_layers]
        layers = [_fm(root=r, name=f"L{i}") for i, r in enumerate(roots_ml)]
        p = _preset(layers)
        tests.append((f"multilayer_{n_layers}", f"FM {n_layers}-layer stack",
                       lambda _p=p: render(_p)))

    # Noise texture
    for noise in ([0.0, 0.3, 1.0] if not quick else [0.3]):
        p = _preset([_fm(noise_amount=noise)])
        tests.append((f"noise_{noise}", f"FM noise={noise}",
                       lambda _p=p: render(_p)))

    # Trajectories
    for traj in (["orbit", "pendulum", "drift", "spiral"] if not quick else ["orbit"]):
        p = _preset([_fm(trajectory_x=traj, speed=0.1)])
        tests.append((f"trajectory_{traj}", f"FM trajectory={traj}",
                       lambda _p=p: render(_p)))

    # 5-layer max-mix: verify summing 5 loud layers doesn't clip
    five_roots = [55, 110, 165, 220, 330]
    five_layers = [_fm(root=r, name=f"L{i}", amp_min=0.02, amp_max=0.06)
                   for i, r in enumerate(five_roots)]
    p = _preset(five_layers)
    tests.append(("5layer_max_mix", "FM 5-layer dense stack (clipping check)",
                   lambda _p=p: render(_p)))

    return tests


def suite_sub(quick: bool) -> list[tuple]:
    tests = []

    for wf in (["saw", "square", "triangle"] if not quick else ["saw", "square"]):
        p = _preset([_sub(waveform=wf)])
        tests.append((f"waveform_{wf}", f"Sub waveform={wf}",
                       lambda _p=p: render(_p)))

    for dt in ([0, 10, 50, 100] if not quick else [8, 50]):
        p = _preset([_sub(detune_cents=dt)])
        tests.append((f"detune_{dt}ct", f"Sub detune={dt}¢",
                       lambda _p=p: render(_p)))

    for ftype in (["lp", "hp", "bp"] if not quick else ["lp"]):
        p = _preset([_sub(filter_type=ftype, filter_lfo_depth=0.6, filter_lfo_rate=1.0)])
        tests.append((f"filter_{ftype}_lfo", f"Sub {ftype} + fast LFO",
                       lambda _p=p: render(_p)))

    # Sub mix extremes
    for sm in ([0.0, 0.5, 1.0] if not quick else [0.3]):
        p = _preset([_sub(sub_mix=sm)])
        tests.append((f"sub_mix_{sm}", f"Sub sub_mix={sm}",
                       lambda _p=p: render(_p)))

    # Distortion
    for drive in ([0.0, 0.5, 1.0] if not quick else [0.5]):
        p = _preset([_sub(distortion_drive=drive, distortion_type="soft")])
        tests.append((f"dist_drive_{drive}", f"Sub distortion_drive={drive}",
                       lambda _p=p: render(_p)))

    # Filter stability: high resonance + fast LFO (can cause IIR runaway → NaN)
    p = _preset([_sub(filter_type="lp", filter_cutoff=600, filter_resonance=8.0,
                      filter_lfo_rate=2.0, filter_lfo_depth=0.9)])
    tests.append(("filter_highq_lfo", "Sub high-Q filter (resonance=8) + fast LFO",
                   lambda _p=p: render(_p)))

    return tests


def suite_gran(quick: bool) -> list[tuple]:
    tests = []

    # Collect available sample files
    ogg_files = sorted(f.name for f in SAMPLES_DIR.glob("*.ogg"))
    wav_files = sorted(f.name for f in SAMPLES_DIR.glob("*.wav"))
    all_samples = ogg_files + wav_files
    if quick:
        all_samples = ["singing_bowl.ogg", "gong.ogg", "metal_resonance.ogg",
                       "alien_mountains.wav", "throat_singing.ogg"]

    # Every sample — default settings
    for src in all_samples:
        p = _preset([_gran(source=src)])
        tests.append((f"src_{Path(src).stem}", f"Granular source={src}",
                       lambda _p=p: render(_p)))

    # Pitch modes × semitones
    modes = ["resample", "stretch", "energetic"]
    semitones = ([-12, 0, +12] if not quick else [0, +7])
    for mode in modes:
        for st in semitones:
            p = _preset([_gran(source="singing_bowl.ogg",
                                pitch_mode=mode, pitch_semitones=st)])
            tests.append((f"pitchmode_{mode}_st{st:+d}",
                           f"Gran mode={mode} pitch={st:+d}st",
                           lambda _p=p: render(_p)))

    # Grain size extremes
    for gs in ([20, 50, 80, 150, 200] if not quick else [20, 80, 200]):
        p = _preset([_gran(grain_size=gs)])
        tests.append((f"grainsize_{gs}ms", f"Gran grain_size={gs}ms",
                       lambda _p=p: render(_p)))

    # Density extremes
    for density in ([1, 5, 15, 30, 50] if not quick else [5, 30]):
        p = _preset([_gran(density=density)])
        tests.append((f"density_{density}", f"Gran density={density}/s",
                       lambda _p=p: render(_p)))

    # Position modes
    for pmode in (["linear", "random"] if not quick else ["random"]):
        p = _preset([_gran(position_mode=pmode, position_chaos=0.7)])
        tests.append((f"posmode_{pmode}", f"Gran position_mode={pmode}",
                       lambda _p=p: render(_p)))

    # Envelopes
    for env in (["hann", "triangle"] if not quick else ["triangle"]):
        p = _preset([_gran(envelope=env)])
        tests.append((f"envelope_{env}", f"Gran envelope={env}",
                       lambda _p=p: render(_p)))

    # Pitch spread extremes
    for ps in ([0.0, 0.5, 2.0] if not quick else [0.0, 1.0]):
        p = _preset([_gran(pitch_spread=ps)])
        tests.append((f"pitchspread_{ps}", f"Gran pitch_spread={ps}st",
                       lambda _p=p: render(_p)))

    # Multi-granular layers
    p = _preset([
        _gran(source="singing_bowl.ogg", name="G1"),
        _gran(source="gong.ogg",         name="G2"),
    ])
    tests.append(("multilayer_2gran", "Gran 2-layer granular mix",
                   lambda _p=p: render(_p)))

    return tests


def suite_fx(quick: bool) -> list[tuple]:
    tests = []
    base = _fm(root=220)

    # Reverb spaces
    spaces = ["room", "hall", "cathedral", "cave"] if not quick else ["hall", "cathedral"]
    for mix in ([0.2, 0.5, 0.9] if not quick else [0.4]):
        for space in spaces:
            p = _preset([base], reverb={"enabled": True, "space": space,
                                         "mix": mix, "decay_trim": 1.0,
                                         "pre_delay_ms": 0.0})
            tests.append((f"reverb_{space}_mix{mix}",
                           f"Reverb space={space} mix={mix}",
                           lambda _p=p: render(_p)))

    # Reverb pre-delay
    for delay in ([0, 20, 50, 100, 150] if not quick else [0, 50]):
        p = _preset([base], reverb={"enabled": True, "space": "hall",
                                     "mix": 0.4, "decay_trim": 1.0,
                                     "pre_delay_ms": delay})
        tests.append((f"reverb_predelay_{delay}ms",
                       f"Reverb pre_delay={delay}ms",
                       lambda _p=p: render(_p)))

    # Earth
    for pressure in ([0.1, 0.4, 0.8] if not quick else [0.4]):
        p = _preset([base], earth={"enabled": True, "tectonic_frequency": 18,
                                    "pressure": pressure, "movement": 0.02})
        tests.append((f"earth_pressure_{pressure}",
                       f"Earth pressure={pressure}",
                       lambda _p=p: render(_p)))

    # Air
    for intensity in ([0.05, 0.2, 0.5] if not quick else [0.15]):
        p = _preset([base], air={"enabled": True, "intensity": intensity,
                                  "movement": 0.02, "turbulence": 0.04})
        tests.append((f"air_intensity_{intensity}",
                       f"Air intensity={intensity}",
                       lambda _p=p: render(_p)))

    # Flanger
    for wet in ([0.0, 0.4, 0.9] if not quick else [0.5]):
        p = _preset([base], flanger={"rate": 0.3, "depth": 0.6,
                                      "feedback": 0.4, "wet": wet})
        tests.append((f"flanger_wet_{wet}", f"Flanger wet={wet}",
                       lambda _p=p: render(_p)))

    # Saturation
    for sat in ([0.0, 0.3, 0.7, 1.0] if not quick else [0.3, 1.0]):
        p = _preset([base], saturation=sat)
        tests.append((f"saturation_{sat}", f"Saturation={sat}",
                       lambda _p=p: render(_p)))

    # All FX combined
    p = _preset(
        [_fm(root=110), _gran(source="singing_bowl.ogg")],
        saturation=0.3,
        reverb={"enabled": True, "space": "hall", "mix": 0.3, "decay_trim": 1.0,
                "pre_delay_ms": 20.0},
        earth={"enabled": True, "tectonic_frequency": 18, "pressure": 0.3, "movement": 0.02},
        air={"enabled": True, "intensity": 0.1, "movement": 0.01, "turbulence": 0.03},
        flanger={"rate": 0.2, "depth": 0.4, "feedback": 0.3, "wet": 0.2},
    )
    tests.append(("all_fx_combined", "All FX combined (FM+Gran+Reverb+Earth+Air+Flanger)",
                   lambda _p=p: render(_p)))

    return tests


def suite_transition(quick: bool) -> list[tuple]:
    tests = []

    combos = [
        ("fm_to_fm",     _preset([_fm(root=220)]),       _preset([_fm(root=440)])),
        ("fm_to_sub",    _preset([_fm(root=220)]),       _preset([_sub(waveform="saw")])),
        ("fm_to_gran",   _preset([_fm(root=220)]),       _preset([_gran("singing_bowl.ogg")])),
        ("sub_to_gran",  _preset([_sub(waveform="saw")]), _preset([_gran("gong.ogg")])),
        ("gran_to_gran", _preset([_gran("singing_bowl.ogg")]), _preset([_gran("metal_resonance.ogg")])),
    ]
    if quick:
        combos = combos[:2]

    for name, pa, pb in combos:
        for cf in ([0.5, 2.0, 4.0] if not quick else [2.0]):
            p_a, p_b = pa, pb
            # Global click check (full 8s render)
            tests.append((f"{name}_cf{cf}s",
                           f"Reload {name} crossfade={cf}s",
                           lambda _pa=p_a, _pb=p_b, _cf=cf:
                               render_with_reload(_pa, _pb, crossfade=_cf)))
            # Seam-zoom: only the crossfade window ± 0.5s (catches subtle transition clicks)
            tests.append((f"{name}_cf{cf}s_seam",
                           f"Seam zoom {name} crossfade={cf}s",
                           lambda _pa=p_a, _pb=p_b, _cf=cf:
                               render_seam_slice(_pa, _pb, crossfade=_cf)))

    # Tuning retune click: simulate applyTuning() — reload with same structure
    # but different layer root frequencies (just intonation vs equal temperament).
    # Uses a very short crossfade (50ms) matching the UI retune behaviour.
    _base_root = 220.0
    _just_ratio = 9.0 / 8.0          # major 2nd in just intonation
    pa_tune = _preset([_fm(root=_base_root)])
    pb_tune = _preset([_fm(root=_base_root * _just_ratio)])
    for cf_ms in ([50, 200, 500] if not quick else [50, 200]):
        cf_s = cf_ms / 1000.0
        tests.append((f"tuning_retune_cf{cf_ms}ms",
                       f"Tuning retune (crossfade={cf_ms}ms)",
                       lambda _pa=pa_tune, _pb=pb_tune, _cf=cf_s:
                           render_with_reload(_pa, _pb, crossfade=_cf,
                                              duration=_cf * 2 + 2.0)))

    # Rapid reload stress test: 3 reloads in 9 seconds
    def _rapid_reload():
        presets = [
            _preset([_fm(root=110)]),
            _preset([_fm(root=220)]),
            _preset([_gran("singing_bowl.ogg")]),
            _preset([_sub(waveform="square")]),
        ]
        engine = StreamingDroneEngine(presets[0], seed=42)
        total = int(9 * SR)
        reload_every = total // 4
        chunks = []
        rendered = 0
        reload_idx = 1
        while rendered < total:
            if reload_idx < len(presets) and rendered >= reload_idx * reload_every:
                engine.reload(presets[reload_idx], crossfade_secs=1.0)
                reload_idx += 1
            n = min(CHUNK_SIZE, total - rendered)
            chunks.append(engine.next_chunk(n))
            rendered += n
        return np.concatenate(chunks, axis=0)

    if not quick:
        tests.append(("rapid_reload_stress", "3 hot-reloads in 9s (stress test)",
                       _rapid_reload))

    return tests


def suite_stability(quick: bool) -> list[tuple]:
    """Long renders (30s) to catch late-onset issues: FM drift, reverb divergence,
    granular position walk going silent, filter runaway over time."""
    tests = []
    LONG = 30  # seconds

    # FM long render (with and without reverb)
    tests.append(("fm_long_30s", "FM long render 30s",
                   lambda: render(_preset([_fm(root=110)]), duration=LONG)))

    tests.append(("fm_reverb_long_30s", "FM + reverb long render 30s",
                   lambda: render(
                       _preset([_fm(root=110)],
                               reverb={"enabled": True, "space": "hall", "mix": 0.4,
                                       "decay_trim": 1.0, "pre_delay_ms": 20.0}),
                       duration=LONG)))

    # Subtractive with filter LFO (long — can diverge with resonance)
    tests.append(("sub_filter_long_30s", "Sub filter+LFO long render 30s",
                   lambda: render(
                       _preset([_sub(filter_type="lp", filter_cutoff=800,
                                     filter_resonance=4.0, filter_lfo_rate=0.3,
                                     filter_lfo_depth=0.7)]),
                       duration=LONG)))

    # Granular long render — position walk should not go silent
    tests.append(("gran_long_30s", "Granular long render 30s",
                   lambda: render(
                       _preset([_gran(source="singing_bowl.ogg",
                                      position_mode="linear", position_chaos=0.3)]),
                       duration=LONG)))

    # Energetic mode — check RMS burst from transient density spikes
    tests.append(("gran_energetic_long_30s", "Granular energetic long render 30s",
                   lambda: render(
                       _preset([_gran(source="singing_bowl.ogg",
                                      pitch_mode="energetic", density=15)]),
                       duration=LONG)))

    # All layers + all FX long render
    if not quick:
        tests.append(("all_fx_long_30s", "All FX long render 30s",
                       lambda: render(
                           _preset(
                               [_fm(root=110), _gran(source="singing_bowl.ogg"),
                                _sub(waveform="saw")],
                               saturation=0.3,
                               reverb={"enabled": True, "space": "hall", "mix": 0.3,
                                       "decay_trim": 1.0, "pre_delay_ms": 20.0},
                               earth={"enabled": True, "tectonic_frequency": 18,
                                      "pressure": 0.3, "movement": 0.02},
                               air={"enabled": True, "intensity": 0.1,
                                    "movement": 0.01, "turbulence": 0.03},
                           ),
                           duration=LONG)))

    return tests


def suite_presets(quick: bool) -> list[tuple]:
    """Test every .yaml preset in shared/."""
    from engine.preset_loader import load_preset

    tests = []
    yaml_files = sorted(SHARED_DIR.glob("*.yaml")) if SHARED_DIR.exists() else []

    for yf in yaml_files:
        name = yf.stem
        try:
            preset = load_preset(yf)
        except Exception as e:
            err = str(e)
            tests.append((name, f"Preset: {yf.name}",
                           lambda _e=err: (_ for _ in ()).throw(ValueError(_e))))
            continue

        # Use full 8s to exercise more of the render
        tests.append((name, f"Preset: {yf.name}",
                       lambda _p=preset: render(_p, duration=8)))

    return tests


# ═════════════════════════════════════════════════════════════════════════════
# Output / reporting
# ═════════════════════════════════════════════════════════════════════════════

R = "\033[0m"
G = "\033[92m"
RE = "\033[91m"
Y = "\033[93m"
C = "\033[96m"
D = "\033[2m"
B = "\033[1m"

_SECTION_LABELS = {
    "fm":         "FM Synthesis",
    "sub":        "Subtractive",
    "gran":       "Granular",
    "fx":         "Global FX",
    "transition": "Transitions / Hot-Reload",
    "stability":  "Long-Render Stability",
    "presets":    "Shared Presets",
}


def print_result(r: Result, verbose: bool):
    status = f"{G}✓{R}" if r.passed else f"{RE}✗{R}"
    t_str  = f"{D}{r.elapsed:.1f}s{R}"
    print(f"  {status}  {r.name:<50} {t_str}")
    if not r.passed:
        for issue in r.issues:
            print(f"       {Y}⚠  {issue}{R}")
        if r.error:
            for line in r.error.strip().split("\n")[-5:]:
                print(f"       {D}{line}{R}")
    elif verbose and r.metrics:
        m = r.metrics
        print(f"       {D}rms={m['rms']:.5f}  peak={m['peak']:.3f}  "
              f"clicks={m['click_count']}  bndry={m['boundary_clicks']}  "
              f"dc={m['dc']:.5f}  rms_spike={m.get('rms_spike',1.0):.1f}x{R}")


def save_flagged_renders(results: list[Result]) -> int:
    FLAGGED_DIR.mkdir(exist_ok=True)
    saved = 0
    for r in results:
        if not r.passed and r.audio is not None and not r.error:
            path = FLAGGED_DIR / f"{r.section}__{r.name}.wav"
            sf.write(str(path), r.audio, SR, format="WAV", subtype="PCM_16")
            saved += 1
    return saved


# ═════════════════════════════════════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════════════════════════════════════

SUITES = {
    "fm":         suite_fm,
    "sub":        suite_sub,
    "gran":       suite_gran,
    "fx":         suite_fx,
    "transition": suite_transition,
    "stability":  suite_stability,
    "presets":    suite_presets,
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mantice audio quality regression tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--quick",        action="store_true",
                        help="Run a fast subset (~60 tests)")
    parser.add_argument("--save-flagged", action="store_true",
                        help=f"Save failed renders as WAV to {FLAGGED_DIR.name}/")
    parser.add_argument("--verbose",      action="store_true",
                        help="Print metrics for passing tests")
    parser.add_argument("--section",
                        choices=[*SUITES, "all"], default="all",
                        help="Run only one section (default: all)")
    args = parser.parse_args()

    sections = list(SUITES) if args.section == "all" else [args.section]

    # Build full test list as (section, name, desc, fn)
    all_tests: list[tuple] = []
    for sec in sections:
        for name, desc, fn in SUITES[sec](args.quick):
            all_tests.append((sec, name, desc, fn))

    total = len(all_tests)
    mode  = "QUICK" if args.quick else "FULL"

    print(f"\n{B}{'━'*65}")
    print(f"  Mantice Audio Quality Test Suite  [{mode}]")
    print(f"  SR={SR}Hz  chunk={CHUNK_SIZE}  duration={TEST_DURATION}s/test")
    print(f"  {total} tests across {len(sections)} section(s)")
    print(f"{'━'*65}{R}\n")

    results: list[Result] = []
    current_sec = None
    t_suite_start = time.time()

    for sec, name, desc, fn in all_tests:
        if sec != current_sec:
            current_sec = sec
            label = _SECTION_LABELS.get(sec, sec)
            print(f"\n  {B}{C}── {label} {'─'*(48 - len(label))}{R}")

        r = run_test(sec, name, desc, fn, keep_audio=args.save_flagged)
        results.append(r)
        print_result(r, args.verbose)

    # ── Summary ───────────────────────────────────────────────────────────────
    total_time = time.time() - t_suite_start
    passed = sum(1 for r in results if r.passed)
    failed = total - passed

    print(f"\n{B}{'━'*65}")
    print(f"  {G}{passed} passed{R}  {(RE+str(failed)+' failed'+R) if failed else str(failed)+' failed'}  "
          f"/ {total} total  ({total_time:.0f}s)")

    if failed:
        print(f"\n  {Y}Failed:{R}")
        for r in results:
            if not r.passed:
                iss = " | ".join(r.issues[:2])
                print(f"    {RE}✗{R}  {r.section}/{r.name}  {D}{iss}{R}")

    if args.save_flagged:
        n_saved = save_flagged_renders(results)
        if n_saved:
            print(f"\n  {Y}⬇  Saved {n_saved} flagged render(s) → {FLAGGED_DIR}{R}")

    print(f"{'━'*65}{R}\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
