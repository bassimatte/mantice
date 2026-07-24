#!/usr/bin/env python3
"""Measure Mantice's permanent cross-path sonic reference set.

The suite compares direct Python preset loading with website UI reconstruction,
then guards broad perceptual metrics for live preview and balanced offline
rendering. Use ``--measure`` to print a candidate baseline after an intentional
sonic change; baseline updates should always be reviewed by listening.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path

import numpy as np

from engine.convolution_reverb import apply_convolution_reverb
from engine.post_processing import (
    integrated_loudness,
    loudness_normalize,
    oversampled_saturate,
)
from engine.preset_loader import load_preset
from engine.streaming_engine import StreamingDroneEngine
from engine.web_server import _preset_to_ui_params, _ui_params_to_preset


ROOT = Path(__file__).resolve().parent
BASELINE_PATH = ROOT / "sonic_reference_baseline.json"
SAMPLE_RATE = 22_050
SEED = 42
REFERENCE_DURATION_SECONDS = 4.0
REFERENCE_PRESETS = {
    "single_low_drone": "presets/essentials/Simple Drone.yaml",
    "bright_fm": "presets/cinematic/Solar Flare.yaml",
    "dense_cinematic": "presets/cinematic/Cosmic Expanse.yaml",
    "granular": "presets/experimental/Grain Cloud.yaml",
    "wavetable": "presets/experimental/Tremor Cartography.yaml",
    "subharmonic": "presets/subharmonic/Void Monolith.yaml",
    "shimmer": "presets/sacred/Cathedral Ascension.yaml",
}
TOLERANCES = {
    "lufs": 1.5,
    "peak": 0.12,
    "crest_db": 2.5,
    "centroid_ratio": 0.25,
    "low_band_ratio": 0.15,
    "stereo_correlation": 0.18,
}


def render_stream(
    preset: dict,
    *,
    duration: float,
    preview_loudness: bool,
    render_mode: bool = False,
    chunk_size: int = 2048,
) -> np.ndarray:
    preset = copy.deepcopy(preset)
    preset["duration"] = duration
    engine = StreamingDroneEngine(
        preset,
        seed=SEED,
        render_mode=render_mode,
        preview_loudness=preview_loudness,
    )
    remaining = int(duration * engine.SR)
    chunks = []
    while remaining:
        count = min(chunk_size, remaining)
        chunks.append(engine.next_chunk(count))
        remaining -= count
    return np.concatenate(chunks)


def render_balanced_offline(preset: dict, duration: float) -> np.ndarray:
    """Render the common standard-quality website/Python offline signal path."""
    source = copy.deepcopy(preset)
    source["duration"] = duration
    reverb = dict(source.get("reverb") or {})
    reverb_enabled = bool(reverb.get("enabled", False))
    if reverb_enabled:
        source["reverb"] = {**reverb, "enabled": False}
    saturation = float(source.get("saturation", 0.3))
    source["saturation"] = 0.0

    audio = render_stream(
        source,
        duration=duration,
        preview_loudness=False,
        render_mode=False,
    )
    if saturation > 0.01:
        audio = oversampled_saturate(audio, saturation)
    if reverb_enabled:
        audio = apply_convolution_reverb(
            audio,
            space=reverb.get("space", "cathedral"),
            mix=float(reverb.get("mix", 0.3)),
            decay_trim=float(reverb.get("decay_trim", 1.0)),
            sr=SAMPLE_RATE,
        )
    return loudness_normalize(audio, SAMPLE_RATE)


def metrics(audio: np.ndarray) -> dict[str, float]:
    stereo = np.asarray(audio, dtype=np.float64)
    mono = np.mean(stereo, axis=1)
    peak = float(np.max(np.abs(stereo)))
    rms = float(np.sqrt(np.mean(mono * mono)))
    crest_db = 20.0 * math.log10(max(peak, 1e-12) / max(rms, 1e-12))

    windowed = mono * np.hanning(len(mono))
    spectrum = np.abs(np.fft.rfft(windowed))
    frequencies = np.fft.rfftfreq(len(mono), 1.0 / SAMPLE_RATE)
    spectral_sum = float(np.sum(spectrum))
    centroid = (
        float(np.sum(frequencies * spectrum) / spectral_sum)
        if spectral_sum > 1e-12 else 0.0
    )
    power = spectrum * spectrum
    total_power = float(np.sum(power))
    low_ratio = (
        float(np.sum(power[frequencies < 120.0]) / total_power)
        if total_power > 1e-18 else 0.0
    )

    left = stereo[:, 0] - np.mean(stereo[:, 0])
    right = stereo[:, 1] - np.mean(stereo[:, 1])
    denominator = float(np.sqrt(np.sum(left * left) * np.sum(right * right)))
    correlation = (
        float(np.sum(left * right) / denominator)
        if denominator > 1e-18 else 0.0
    )
    return {
        "lufs": round(float(integrated_loudness(stereo, SAMPLE_RATE)), 3),
        "peak": round(peak, 6),
        "crest_db": round(crest_db, 3),
        "centroid_hz": round(centroid, 3),
        "low_band_ratio": round(low_ratio, 6),
        "stereo_correlation": round(correlation, 6),
    }


def measure_reference_set(duration: float) -> tuple[dict, list[str]]:
    measured: dict[str, dict] = {}
    failures: list[str] = []
    for label, relative_path in REFERENCE_PRESETS.items():
        direct = load_preset(ROOT / relative_path)
        reconstructed = _ui_params_to_preset(_preset_to_ui_params(direct))

        direct_offline = render_balanced_offline(direct, duration)
        website_offline = render_balanced_offline(reconstructed, duration)
        parity_error = float(np.max(np.abs(direct_offline - website_offline)))
        if parity_error > 1e-5:
            failures.append(
                f"{label}: Python/website reconstruction differs "
                f"(max sample error {parity_error:.7f})"
            )

        live = render_stream(
            reconstructed,
            duration=duration,
            preview_loudness=True,
            render_mode=False,
            chunk_size=1024,
        )
        measured[label] = {
            "preset": relative_path,
            "offline": metrics(direct_offline),
            "live": metrics(live),
            "roundtrip_max_error": round(parity_error, 9),
        }
        print(f"measured {label}", file=sys.stderr, flush=True)
    return measured, failures


def compare_metrics(measured: dict, baseline: dict) -> list[str]:
    failures: list[str] = []
    for label in REFERENCE_PRESETS:
        if label not in baseline:
            failures.append(f"{label}: missing from sonic baseline")
            continue
        for path_name in ("offline", "live"):
            actual = measured[label][path_name]
            expected = baseline[label][path_name]
            for key in ("lufs", "peak", "crest_db", "low_band_ratio", "stereo_correlation"):
                tolerance = TOLERANCES[key]
                delta = abs(float(actual[key]) - float(expected[key]))
                if delta > tolerance:
                    failures.append(
                        f"{label}/{path_name}/{key}: {actual[key]} "
                        f"(baseline {expected[key]}, tolerance ±{tolerance})"
                    )
            expected_centroid = max(float(expected["centroid_hz"]), 1.0)
            centroid_ratio = abs(
                float(actual["centroid_hz"]) - expected_centroid
            ) / expected_centroid
            if centroid_ratio > TOLERANCES["centroid_ratio"]:
                failures.append(
                    f"{label}/{path_name}/centroid_hz: {actual['centroid_hz']} "
                    f"(baseline {expected['centroid_hz']}, tolerance "
                    f"±{TOLERANCES['centroid_ratio'] * 100:.0f}%)"
                )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--measure",
        action="store_true",
        help="Print current metrics as baseline JSON instead of comparing",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=REFERENCE_DURATION_SECONDS,
        help="Seconds rendered per path and reference (default: 4)",
    )
    args = parser.parse_args()

    measured, failures = measure_reference_set(max(1.0, args.duration))
    if args.measure:
        print(json.dumps(measured, indent=2, sort_keys=True))
    else:
        baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        failures.extend(compare_metrics(measured, baseline))

    if failures:
        print("\nSonic reference failures:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    if not args.measure:
        print(f"All {len(REFERENCE_PRESETS)} sonic references passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
