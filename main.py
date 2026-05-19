"""
main.py — MANTICE V19.0
---------------------
Usage:
    python main.py                              # process all presets
    python main.py --list                       # list available presets
    python main.py --preset path/to.yaml        # single preset by path
    python main.py --name "Breathing Cathedral" # run preset by name
    python main.py --duration 90                # override duration (seconds)
    python main.py --format flac               # export as FLAC (wav, flac, ogg, mp3)
    python main.py --seed 42                    # global reproducibility seed
    python main.py --preview --name "Cavern"   # real-time preview to speakers
    python main.py --preview --infinite        # infinite drone, Ctrl+C to stop
    python main.py --generate                  # generate a random preset
    python main.py --generate --mood dark      # generate with mood bias
    python main.py --gui                       # launch web UI in browser
    python main.py --mutate "Breathing Cathedral" --amount 0.3  # mutate existing
"""

import argparse
import csv
import random
import sys
import time
import warnings
from pathlib import Path
from typing import List, Optional

# ── Hi-res mode must be set before engine imports ────────────────────────────
if "--hires" in sys.argv:
    from engine.config import set_hires
    set_hires()

import numpy as np

from engine.preset_loader import load_preset
from engine.drone_engine  import DroneEngine
from engine.exporter      import export_audio, SUPPORTED_FORMATS
from engine.generator     import generate_preset, mutate_preset, save_generated_preset, get_available_moods

PRESET_DIR = Path("presets")
EXPORT_DIR = Path("exports")

EXPORT_DIR.mkdir(exist_ok=True)

CSV_COLUMNS = [
    "audio_filename", "name", "tags", "geotag",
    "description", "license", "pack_name", "is_explicit", "bst_category",
]


# ── helpers ───────────────────────────────────────────────────────────────────

def discover_presets() -> List[Path]:
    if not PRESET_DIR.exists():
        return []
    return sorted(PRESET_DIR.rglob("*.yaml"))


def apply_seed(preset: dict, cli_seed: Optional[int]) -> None:
    seed = cli_seed if cli_seed is not None else preset.get("seed")
    if seed is not None:
        random.seed(seed)
        np.random.seed(seed)


def build_tags(preset: dict) -> str:
    meta     = preset.get("meta", {})
    mood     = meta.get("mood") or []
    base     = ["drone", "ambient", "spatial", "sacred"]
    category = meta.get("category", "")
    if category and category not in base:
        base.append(category)
    all_tags = base + [m for m in mood if m not in base]
    return ", ".join(all_tags)


def write_metadata_csv(csv_path: Path, audio_filename: str, preset: dict) -> None:
    meta = preset.get("meta", {})
    row  = {
        "audio_filename": audio_filename,
        "name":           meta.get("name", Path(audio_filename).stem),
        "tags":           build_tags(preset),
        "geotag":         "",
        "description":    meta.get("description", "Procedural sacred drone."),
        "license":        "Creative Commons 0",
        "pack_name":      "Drones",
        "is_explicit":    0,
        "bst_category":   "Drone",
    }
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerow(row)


# ── progress bar ──────────────────────────────────────────────────────────────

class ProgressBar:
    """Simple terminal progress bar (no external dependencies)."""

    def __init__(self, total: int, description: str = "", width: int = 40):
        self.total       = max(total, 1)
        self.description = description
        self.width       = width
        self.current     = 0
        self.start_time  = time.time()

    def update(self, n: int = 1) -> None:
        self.current = min(self.current + n, self.total)
        self._render()

    def _render(self) -> None:
        frac    = self.current / self.total
        filled  = int(self.width * frac)
        bar     = "█" * filled + "░" * (self.width - filled)
        percent = frac * 100
        elapsed = time.time() - self.start_time

        if self.current > 0 and frac < 1.0:
            eta = elapsed / frac * (1 - frac)
            time_str = f"ETA {eta:.0f}s"
        elif frac >= 1.0:
            time_str = f"{elapsed:.1f}s"
        else:
            time_str = "..."

        line = f"\r  {self.description} |{bar}| {percent:5.1f}% {time_str}"
        sys.stdout.write(line)
        sys.stdout.flush()

    def finish(self) -> None:
        self.current = self.total
        self._render()
        sys.stdout.write("\n")
        sys.stdout.flush()


# ── main ──────────────────────────────────────────────────────────────────────

def run(
    preset_paths: List[Path],
    cli_seed: Optional[int],
    cli_duration: Optional[float],
    audio_format: str,
    solo_layer: Optional[str] = None,
) -> None:
    ok = failed = 0
    total = len(preset_paths)

    for idx, preset_path in enumerate(preset_paths, 1):
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                preset = load_preset(preset_path)
                for w in caught:
                    print(f"  ⚠  {w.message}")

            # Override duration from CLI if specified
            if cli_duration is not None:
                preset["duration"] = cli_duration

            apply_seed(preset, cli_seed)

            name = preset["meta"].get("name", preset_path.stem)
            slug = preset["meta"].get("slug", preset_path.stem.lower().replace(" ", "_"))

            # ── Solo layer: disable all except the target ─────────────────
            solo_layer_name = None
            if solo_layer is not None:
                layers = preset["layers"]
                target_idx = None
                # Try as index first
                try:
                    idx_val = int(solo_layer)
                    if 0 <= idx_val < len(layers):
                        target_idx = idx_val
                except ValueError:
                    pass
                # Try as name match
                if target_idx is None:
                    query = solo_layer.lower()
                    for i, l in enumerate(layers):
                        if query in l.get("name", "").lower():
                            target_idx = i
                            break
                if target_idx is None:
                    print(f"  ✗ Layer '{solo_layer}' not found. Available layers:")
                    for i, l in enumerate(layers):
                        print(f"      {i}: {l.get('name', 'Layer ' + str(i))}")
                    failed += 1
                    continue
                # Disable all except target
                for i, l in enumerate(layers):
                    l["enabled"] = (i == target_idx)
                solo_layer_name = layers[target_idx].get("name", f"Layer {target_idx}")
                print(f"\n[{idx}/{total}] Generating: {name} — solo: {solo_layer_name}")
            else:
                print(f"\n[{idx}/{total}] Generating: {name}")

            # Build with progress callback
            engine = DroneEngine(preset)

            n_layers = len([l for l in preset["layers"] if l.get("enabled", True)])
            has_earth = bool(preset.get("earth") and preset["earth"].get("enabled", True))
            has_air = bool(preset.get("air") and preset["air"].get("enabled", True))
            has_reverb = bool(preset.get("reverb") and preset["reverb"].get("enabled", True))
            total_steps = n_layers + int(has_earth) + int(has_air) + int(has_reverb) + 2

            progress = ProgressBar(total_steps, description="Building")
            audio = engine.build(progress_callback=progress.update)
            progress.finish()

            # Export audio — append layer name if solo
            if solo_layer_name:
                safe_name = "".join(c for c in name if c.isalnum() or c in " -_").strip()
                safe_layer = "".join(c for c in solo_layer_name if c.isalnum() or c in " -_").strip()
                audio_filename = f"{safe_name} - Solo {safe_layer}.{audio_format}"
            else:
                audio_filename = f"{slug}.{audio_format}"
            out_path = EXPORT_DIR / audio_filename
            export_audio(out_path, audio, fmt=audio_format)
            print(f"  ✓ Saved: {out_path}")

            csv_path = EXPORT_DIR / f"{slug}.csv"
            write_metadata_csv(csv_path, audio_filename, preset)

            ok += 1

        except Exception as exc:
            print(f"  ✗ Failed ({preset_path.name}): {exc}", file=sys.stderr)
            failed += 1

    print(f"\n{'─' * 40}")
    print(f"Done — {ok} exported, {failed} failed.")


def list_presets(preset_paths: List[Path]) -> None:
    """Print available presets in a readable table."""
    print(f"{'#':<4} {'Name':<30} {'Category':<14} {'Duration':<10} Path")
    print("─" * 90)
    for i, p in enumerate(preset_paths, 1):
        try:
            with warnings.catch_warnings(record=True):
                warnings.simplefilter("always")
                preset = load_preset(p)
            meta = preset.get("meta", {})
            name = meta.get("name", p.stem)
            cat  = meta.get("category", "—")
            dur  = f"{preset['duration']:.0f}s"
        except Exception:
            name, cat, dur = p.stem, "?", "?"
        print(f"{i:<4} {name:<30} {cat:<14} {dur:<10} {p}")
    print(f"\n{len(preset_paths)} preset(s) found.")


def find_preset_by_name(preset_paths: List[Path], name: str) -> List[Path]:
    """Find presets whose name or filename matches the query (case-insensitive)."""
    query = name.lower()
    matches = []
    for p in preset_paths:
        # Match against filename stem
        if query in p.stem.lower():
            matches.append(p)
            continue
        # Match against meta.name inside the file
        try:
            with warnings.catch_warnings(record=True):
                warnings.simplefilter("always")
                preset = load_preset(p)
            meta_name = preset.get("meta", {}).get("name", "")
            if query in meta_name.lower():
                matches.append(p)
        except Exception:
            pass
    return matches


def main() -> None:
    available_moods = get_available_moods()

    parser = argparse.ArgumentParser(description="Mantice V19.0")
    parser.add_argument(
        "--gui", action="store_true",
        help="Launch the web UI in your browser (requires fastapi & uvicorn)",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List all available presets and exit",
    )
    parser.add_argument(
        "--preview", action="store_true",
        help="Real-time preview: stream audio to speakers (requires sounddevice)",
    )
    parser.add_argument(
        "--infinite", action="store_true",
        help="Infinite mode: drone plays forever until Ctrl+C (use with --preview)",
    )
    parser.add_argument(
        "--generate", action="store_true",
        help="Generate a random preset and save to presets/generated/",
    )
    parser.add_argument(
        "--mood", type=str, default=None,
        choices=available_moods,
        help=f"Mood bias for --generate. Options: {', '.join(available_moods)}",
    )
    parser.add_argument(
        "--generate-count", type=int, default=1,
        help="Number of presets to generate (default: 1)",
    )
    parser.add_argument(
        "--mutate", type=str, default=None, metavar="PRESET_NAME",
        help="Mutate an existing preset (by name) and save variation to presets/generated/",
    )
    parser.add_argument(
        "--amount", type=float, default=0.3,
        help="Mutation amount (0.0 = identical, 1.0 = wild). Default: 0.3",
    )
    parser.add_argument(
        "--preset", type=Path, default=None,
        help="Path to a single preset file (.yaml)",
    )
    parser.add_argument(
        "--name", type=str, default=None,
        help="Run preset(s) matching this name (case-insensitive search)",
    )
    parser.add_argument(
        "--duration", type=float, default=None,
        help="Override audio duration in seconds (overrides preset value)",
    )
    parser.add_argument(
        "--format", type=str, default="wav",
        choices=SUPPORTED_FORMATS,
        help=f"Audio export format (default: wav). Supported: {', '.join(SUPPORTED_FORMATS)}",
    )
    parser.add_argument(
        "--hires", action="store_true",
        help="Render in high-resolution mode (48kHz/24-bit instead of default 44.1kHz/16-bit)",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Global random seed for reproducible output",
    )
    parser.add_argument(
        "--solo", type=str, default=None, metavar="LAYER",
        help="Render only a single layer (by name or index, e.g. '0' or 'Gravitational Bass'). "
             "Output filename includes layer name.",
    )
    args = parser.parse_args()

    # ── Hi-res mode ──────────────────────────────────────────────────────
    if args.hires:
        from engine.config import set_hires
        set_hires()

    # ── GUI mode ──────────────────────────────────────────────────────────
    if args.gui:
        try:
            from engine.web_server import launch_gui
        except ImportError as e:
            sys.exit(
                f"Web UI requires additional packages:\n"
                f"  pip install fastapi uvicorn[standard]\n\n"
                f"Error: {e}"
            )
        launch_gui()
        return

    generated_dir = PRESET_DIR / "generated"

    # ── Generate mode ─────────────────────────────────────────────────────
    if args.generate:
        print(f"Generating {args.generate_count} preset(s)"
              f"{f' (mood: {args.mood})' if args.mood else ''}...\n")
        for i in range(args.generate_count):
            preset_seed = (args.seed + i) if args.seed is not None else None
            preset = generate_preset(mood=args.mood, seed=preset_seed)
            path = save_generated_preset(preset, generated_dir)
            name = preset["meta"]["name"]
            print(f"  {i+1}. {name}")
            print(f"     → {path}")
        print(f"\n✓ {args.generate_count} preset(s) saved to {generated_dir}/")
        return

    # ── Mutate mode ───────────────────────────────────────────────────────
    if args.mutate:
        all_presets = discover_presets()
        if not all_presets:
            sys.exit(f"No presets found in {PRESET_DIR}/")

        # Find the source preset
        source_paths = find_preset_by_name(all_presets, args.mutate)
        if not source_paths:
            sys.exit(f"No preset matching '{args.mutate}'. Use --list to see available presets.")

        source_path = source_paths[0]
        print(f"Mutating: {source_path.stem} (amount: {args.amount})\n")

        # Load raw YAML for mutation (not normalised)
        import yaml as _yaml
        with source_path.open(encoding="utf-8") as f:
            raw_preset = _yaml.safe_load(f)

        for i in range(args.generate_count):
            mut_seed = (args.seed + i) if args.seed is not None else None
            mutated = mutate_preset(raw_preset, amount=args.amount, seed=mut_seed)
            path = save_generated_preset(mutated, generated_dir)
            name = mutated["meta"]["name"]
            print(f"  {i+1}. {name}")
            print(f"     → {path}")
        print(f"\n✓ {args.generate_count} mutation(s) saved to {generated_dir}/")
        return

    # ── Standard modes ────────────────────────────────────────────────────
    all_presets = discover_presets()

    # --list: print and exit
    if args.list:
        if not all_presets:
            sys.exit(f"No presets found in {PRESET_DIR}/")
        list_presets(all_presets)
        return

    # Determine which preset(s)
    if args.preset:
        if not args.preset.exists():
            sys.exit(f"Preset not found: {args.preset}")
        preset_paths = [args.preset]
    elif args.name:
        if not all_presets:
            sys.exit(f"No presets found in {PRESET_DIR}/")
        preset_paths = find_preset_by_name(all_presets, args.name)
        if not preset_paths:
            sys.exit(f"No preset matching '{args.name}'. Use --list to see available presets.")
        if not args.preview:
            print(f"Matched {len(preset_paths)} preset(s) for '{args.name}'.\n")
    else:
        preset_paths = all_presets
        if not preset_paths:
            sys.exit(f"No presets found in {PRESET_DIR}/")
        if not args.preview:
            print(f"Found {len(preset_paths)} preset(s).\n")

    # ── Preview mode ──────────────────────────────────────────────────────
    if args.preview:
        from engine.preview import PreviewSession

        if len(preset_paths) > 1:
            print(f"Preview uses the first matched preset: {preset_paths[0].stem}")

        session = PreviewSession(
            preset_path       = preset_paths[0],
            infinite          = args.infinite,
            duration_override = args.duration,
        )
        session.start()
        return

    # ── Normal render mode ────────────────────────────────────────────────
    run(preset_paths, cli_seed=args.seed, cli_duration=args.duration,
        audio_format=args.format, solo_layer=args.solo)


if __name__ == "__main__":
    main()
