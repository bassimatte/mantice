#!/usr/bin/env python3
"""Render and report the complete factory library without retuning presets.

Hard failures catch broken, silent, non-finite, or clipping presets. Review
flags expose unusually quiet/loud openings for listening rather than treating
all drones as if they should have identical loudness.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path

import numpy as np

from engine.post_processing import integrated_loudness
from engine.preset_loader import load_preset
from engine.streaming_engine import StreamingDroneEngine


ROOT = Path(__file__).resolve().parent
PRESETS_DIR = ROOT / "presets"
MIN_PEAK = 0.02
MAX_PEAK = 0.96
MIN_LUFS = -32.0
MAX_LUFS = -8.0
REVIEW_QUIET_LUFS = -26.0
REVIEW_LOUD_LUFS = -13.0


def render_opening(path: Path, duration: float) -> tuple[np.ndarray, int]:
    preset = copy.deepcopy(load_preset(path))
    preset["duration"] = duration
    engine = StreamingDroneEngine(
        preset,
        seed=42,
        render_mode=False,
        preview_loudness=True,
    )
    remaining = int(duration * engine.SR)
    chunks = []
    while remaining:
        count = min(1024, remaining)
        chunks.append(engine.next_chunk(count))
        remaining -= count
    return np.concatenate(chunks), engine.SR


def measure(audio: np.ndarray, sample_rate: int) -> dict[str, float | bool]:
    finite = bool(np.all(np.isfinite(audio)))
    safe = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)
    peak = float(np.max(np.abs(safe)))
    mono = np.mean(safe, axis=1)
    rms = float(np.sqrt(np.mean(mono * mono)))
    crest = 20.0 * math.log10(max(peak, 1e-12) / max(rms, 1e-12))
    return {
        "finite": finite,
        "lufs": round(float(integrated_loudness(safe, sample_rate)), 3),
        "peak": round(peak, 6),
        "crest_db": round(crest, 3),
    }


def calibrate(duration: float = 1.5) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    failures: list[str] = []
    for path in sorted(PRESETS_DIR.rglob("*.yaml")):
        relative = path.relative_to(ROOT).as_posix()
        try:
            audio, sample_rate = render_opening(path, duration)
            values = measure(audio, sample_rate)
        except Exception as exc:
            failures.append(f"{relative}: render failed ({exc})")
            continue

        row = {
            "preset": relative,
            "category": path.parent.name,
            **values,
            "review": (
                values["lufs"] < REVIEW_QUIET_LUFS
                or values["lufs"] > REVIEW_LOUD_LUFS
            ),
        }
        rows.append(row)
        if not values["finite"]:
            failures.append(f"{relative}: non-finite audio")
        if values["peak"] < MIN_PEAK:
            failures.append(f"{relative}: effectively silent (peak {values['peak']})")
        if values["peak"] > MAX_PEAK:
            failures.append(f"{relative}: insufficient headroom (peak {values['peak']})")
        if not MIN_LUFS <= values["lufs"] <= MAX_LUFS:
            failures.append(
                f"{relative}: opening loudness {values['lufs']} LUFS is outside "
                f"{MIN_LUFS:g}…{MAX_LUFS:g}"
            )
    return rows, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=1.5)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    rows, failures = calibrate(max(1.0, args.duration))

    if args.json:
        print(json.dumps({"presets": rows, "failures": failures}, indent=2))
    else:
        review = [row for row in rows if row["review"]]
        print(
            f"Measured {len(rows)} factory presets; "
            f"{len(review)} opening(s) flagged for listening review."
        )
        for row in review:
            print(
                f"  REVIEW {row['preset']}: {row['lufs']:.1f} LUFS, "
                f"peak {row['peak']:.3f}"
            )
        for failure in failures:
            print(f"  FAIL {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
