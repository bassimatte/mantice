#!/usr/bin/env python3
"""Run Mantice's release gates from one local or CI entry point."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def run(label: str, command: list[str]) -> None:
    started = time.perf_counter()
    print(f"\n==> {label}", flush=True)
    completed = subprocess.run(command, cwd=ROOT)
    elapsed = time.perf_counter() - started
    if completed.returncode:
        raise SystemExit(
            f"\nFAILED: {label} ({elapsed:.1f}s, exit {completed.returncode})"
        )
    print(f"PASS: {label} ({elapsed:.1f}s)", flush=True)


def verify_frontend_parity() -> None:
    for relative_path in ("index.html", "mantice-ui-core.js"):
        local = (ROOT / "engine" / "static" / relative_path).read_bytes()
        deployed = (ROOT / "docs" / relative_path).read_bytes()
        if local != deployed:
            raise SystemExit(
                "FAILED: frontend parity\n"
                f"engine/static/{relative_path} and docs/{relative_path} differ"
            )
    print("PASS: frontend parity", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--audio",
        choices=("skip", "quick", "full"),
        default="quick",
        help="Audio-quality suite level (default: quick)",
    )
    parser.add_argument(
        "--skip-sonic-reference",
        action="store_true",
        help="Skip the seven-preset cross-path sonic reference suite",
    )
    parser.add_argument(
        "--skip-websocket-smoke",
        action="store_true",
        help="Skip the local end-to-end preview server check",
    )
    args = parser.parse_args()

    verify_frontend_parity()
    run("unit and integration tests", [sys.executable, "-m", "unittest", "discover", "-v"])
    run("fixed-seed generator references", [sys.executable, "generator_reference.py"])
    run("factory-library calibration", [sys.executable, "factory_calibration.py"])
    if not args.skip_sonic_reference:
        run("cross-path sonic references", [sys.executable, "sonic_reference.py"])
    if not args.skip_websocket_smoke:
        run("WebSocket preview smoke", [sys.executable, "websocket_smoke.py"])
    if args.audio != "skip":
        command = [sys.executable, "test_audio_quality.py"]
        if args.audio == "quick":
            command.append("--quick")
        run(f"{args.audio} audio-quality suite", command)

    print("\nAll Mantice release gates passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
