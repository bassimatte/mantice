#!/usr/bin/env python3
"""Verify deterministic and drone-safe generator reference candidates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from engine.generator import generate_preset


ROOT = Path(__file__).resolve().parent
BASELINE_PATH = ROOT / "generator_reference_baseline.json"


def fingerprint(preset: dict) -> str:
    canonical = json.dumps(
        preset,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def usefulness_errors(preset: dict, label: str) -> list[str]:
    errors: list[str] = []
    layers = preset.get("layers") or []
    if not 1 <= len(layers) <= 3:
        errors.append(f"{label}: expected 1–3 layers, got {len(layers)}")

    estimated_cost = 0.0
    for index, layer in enumerate(layers, start=1):
        synth = layer.get("synthesis") or {}
        root = float(synth.get("root", 0))
        voices = int(synth.get("voices", 0))
        if not 20 <= root <= 6000:
            errors.append(f"{label}: layer {index} root {root:g} Hz is invalid")
        if voices < 1:
            errors.append(f"{label}: layer {index} has no voices")
        speed = float((layer.get("spatial_motion") or {}).get("speed", 0))
        if speed > 0.005:
            errors.append(f"{label}: layer {index} movement {speed:g} is too fast")
        lfo_rate = float(layer.get("filter_lfo_rate", 0))
        if lfo_rate > 0.12:
            errors.append(f"{label}: layer {index} filter LFO {lfo_rate:g} Hz is too fast")
        harmonics = int(layer.get("harmonics", 4))
        fm_index = float((layer.get("fm") or {}).get("index", 0))
        estimated_cost += voices * harmonics * (1.0 + fm_index * 0.5)
    if estimated_cost > 500:
        errors.append(f"{label}: estimated synthesis cost {estimated_cost:.1f} > 500")
    return errors


def verify() -> list[str]:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    seeds = baseline["seeds"]
    errors: list[str] = []
    for mood, expected_hashes in baseline["moods"].items():
        actual_hashes = []
        for seed, expected_hash in zip(seeds, expected_hashes):
            label = f"{mood}/{seed}"
            preset = generate_preset(mood, seed=seed)
            actual_hash = fingerprint(preset)
            actual_hashes.append(actual_hash)
            if actual_hash != expected_hash:
                errors.append(
                    f"{label}: fingerprint changed "
                    f"({expected_hash[:10]}… -> {actual_hash[:10]}…)"
                )
            errors.extend(usefulness_errors(preset, label))
        if len(set(actual_hashes)) != len(actual_hashes):
            errors.append(f"{mood}: fixed-seed candidates are not diverse")
    return errors


def main() -> int:
    errors = verify()
    if errors:
        print("Generator reference gate failed:")
        for error in errors:
            print(f"  - {error}")
        return 1
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    total = len(baseline["seeds"]) * len(baseline["moods"])
    print(f"PASS: {total} fixed-seed generator references are stable and useful")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
