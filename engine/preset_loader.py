"""
engine/preset_loader.py
-----------------------
Unified preset loader with preset inheritance.

Accepts:
  - V1 flat JSON  (presets/)
  - V2 grouped YAML (presets_v2/)

Supports:
  - inherits: "parent_name" or "path/to/parent.yaml"
    Deep-merges parent into child (child overrides). Layers are replaced, not merged.
    Supports chained inheritance (grandparent → parent → child).

Returns a normalised internal dict that DroneEngine always works with.
Raises ValueError with a clear message if the preset is invalid.
"""

import copy
import json
import warnings
from pathlib import Path
from typing import Optional

import yaml

from . import config

# ── band inference ────────────────────────────────────────────────────────────

def _infer_band(root_hz: float) -> str:
    if root_hz < 200:
        return "sub"
    if root_hz < 2000:
        return "mid"
    return "high"


# ── deep merge ────────────────────────────────────────────────────────────────

def _deep_merge(base: dict, override: dict) -> dict:
    """
    Recursively merge override into base. Returns a new dict.
    - Dicts are merged recursively (override wins on conflict).
    - Lists and scalars in override replace base entirely.
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


# ── inheritance resolution ────────────────────────────────────────────────────

_MAX_INHERITANCE_DEPTH = 8

def _resolve_parent_path(inherits_value: str, child_path: Path) -> Optional[Path]:
    """
    Resolve the inherits value to an actual file path.
    Accepts:
      - A relative/absolute file path (e.g. "../base/foundation.yaml")
      - A preset name (e.g. "Earth Monolith Ritual") — searched in the presets dir
    """
    # Try as a direct path relative to the child
    candidate = child_path.parent / inherits_value
    if candidate.exists():
        return candidate

    # Try as absolute path
    candidate = Path(inherits_value)
    if candidate.exists():
        return candidate

    # Search by name in the presets directory tree
    presets_root = child_path.parent
    # Walk up to find the presets root (look for a directory that contains categories)
    while presets_root.parent != presets_root:
        if presets_root.name == "presets":
            break
        presets_root = presets_root.parent
    else:
        presets_root = child_path.parent

    # Search for matching filename (case-insensitive)
    query = inherits_value.lower()
    for yaml_file in presets_root.rglob("*.yaml"):
        if yaml_file.stem.lower() == query:
            return yaml_file

    return None


def _load_raw_yaml(path: Path) -> dict:
    """Load raw YAML without normalisation."""
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _resolve_inheritance(raw: dict, child_path: Path, depth: int = 0) -> dict:
    """
    Recursively resolve the 'inherits' chain and return a merged raw dict.
    The child's values override the parent's.
    """
    inherits_value = raw.get("inherits")
    if not inherits_value:
        return raw

    if depth >= _MAX_INHERITANCE_DEPTH:
        raise ValueError(
            f"Inheritance chain too deep (>{_MAX_INHERITANCE_DEPTH} levels) — "
            f"possible circular inheritance at '{child_path.name}'"
        )

    parent_path = _resolve_parent_path(str(inherits_value), child_path)
    if parent_path is None:
        raise ValueError(
            f"Preset '{child_path.name}' inherits from '{inherits_value}' "
            f"but that preset could not be found."
        )

    # Prevent self-inheritance
    if parent_path.resolve() == child_path.resolve():
        raise ValueError(
            f"Preset '{child_path.name}' inherits from itself."
        )

    parent_raw = _load_raw_yaml(parent_path)
    # Recursively resolve parent's own inheritance
    parent_raw = _resolve_inheritance(parent_raw, parent_path, depth + 1)

    # Merge: parent is base, child overrides
    child_overrides = {k: v for k, v in raw.items() if k != "inherits"}
    merged = _deep_merge(parent_raw, child_overrides)

    return merged


# ── layer normalisers ─────────────────────────────────────────────────────────

def _normalize_layer_v1(layer: dict) -> dict:
    """V1 flat layer dict → internal format."""
    root = float(layer["root"])
    return {
        "name":         layer.get("name", "Layer"),
        "enabled":      bool(layer.get("enabled", True)),
        "root":         root,
        "voices":       int(layer["voices"]),
        "ratios":       [float(r) for r in layer.get("ratios", [1.0])],
        "fm_ratios":    [float(r) for r in layer.get("fm_ratios", [1.0])],
        "fm_index":     float(layer.get("fm_index", 0.1)),
        "band":         layer.get("band", _infer_band(root)),
        "mix":          float(layer.get("mix", 1.0)),
        "amp_min":      float(layer.get("amp_min", 0.001)),
        "amp_max":      float(layer.get("amp_max", 0.05)),
        "drift":        float(layer.get("drift", 0.01)),
        "quadrant":     layer.get("quadrant", "center"),
        "speed":        float(layer.get("speed", 0.01)),
        "trajectory_x": layer.get("trajectory_x", "none"),
        "trajectory_y": layer.get("trajectory_y", "none"),
    }


def _normalize_layer_v2(layer: dict) -> dict:
    """V2 grouped YAML layer dict → internal format."""
    layer_type = layer.get("type", "fm")
    synth = layer.get("synthesis", {})
    fm    = layer.get("fm", {})
    dyn   = layer.get("dynamics", {})
    spm   = layer.get("spatial_motion", {})
    root  = float(synth.get("root", 110))
    return {
        "name":         layer.get("name", "Layer"),
        "enabled":      bool(layer.get("enabled", True)),
        "type":         layer_type,
        # FM synthesis keys (used when type == "fm")
        "root":         root,
        "voices":       int(synth.get("voices", 8)),
        "ratios":       [float(r) for r in synth.get("ratios", [1.0])],
        "fm_ratios":    [float(r) for r in fm.get("ratios", [1.0])],
        "fm_index":     float(fm.get("index", 0.1)),
        "band":         layer.get("band", _infer_band(root)),
        "mix":          float(dyn.get("mix", 1.0)),
        "amp_min":      float(dyn.get("amp_min", 0.001)),
        "amp_max":      float(dyn.get("amp_max", 0.05)),
        "drift":        float(dyn.get("drift", 0.01)),
        "quadrant":     spm.get("quadrant", "center"),
        "speed":        float(spm.get("speed", 0.01)),
        "trajectory_x": spm.get("trajectory_x", "none"),
        "trajectory_y": spm.get("trajectory_y", "none"),
        # V15 features
        "harmonics":       int(layer.get("harmonics", 4)),
        "harmonic_decay":  float(layer.get("harmonic_decay", 0.7)),
        "noise_amount":    float(layer.get("noise_amount", 0.0)),
        "noise_color":     layer.get("noise_color", "pink"),
        "elevation":       float(layer.get("elevation", 0.0)),
        "elevation_motion": layer.get("elevation_motion", "static"),
        "elevation_speed": float(layer.get("elevation_speed", 0.1)),
        "elevation_range": float(layer.get("elevation_range", 60.0)),
        # V16 chorus
        "chorus_rate": float(layer.get("chorus_rate", 0.5)),
        "chorus_depth": float(layer.get("chorus_depth", 0.005)),
        "chorus_mix": float(layer.get("chorus_mix", 0.0)),
        "chorus_voices": int(layer.get("chorus_voices", 2)),
        # V21 per-layer filter + LFO
        "filter_type":      layer.get("filter_type", "off"),
        "filter_cutoff":    float(layer.get("filter_cutoff", 2000)),
        "filter_resonance": float(layer.get("filter_resonance", 1.0)),
        "filter_lfo_rate":  float(layer.get("filter_lfo_rate", 0.1)),
        "filter_lfo_depth": float(layer.get("filter_lfo_depth", 0.0)),
        "filter_lfo_shape": layer.get("filter_lfo_shape", "sine"),
        # V21 subtractive synthesis
        "waveform":     layer.get("waveform", "saw"),
        "detune_cents": float(layer.get("detune_cents", 8.0)),
        "sub_mix":      float(layer.get("sub_mix", 0.3)),
        # V17 granular keys
        "source": layer.get("source", "singing_bowl.ogg"),
        "grain_size": float(layer.get("grain_size", 80)),
        "density": float(layer.get("density", 15)),
        "pitch_spread": float(layer.get("pitch_spread", 0.3)),
        "position": float(layer.get("position", 0.5)),
        "scatter": float(layer.get("scatter", 0.5)),
        "envelope": layer.get("envelope", "hann"),
    }


# ── top-level converters ──────────────────────────────────────────────────────

def _from_v1(raw: dict) -> dict:
    meta = raw.get("meta", {})
    return {
        "meta":          meta,
        "seed":          raw.get("seed"),
        "duration":      float(raw.get("duration", 60)),
        "spatial_depth": float(raw.get("spatial_depth", 1.0)),
        "spatial_wet":   float(raw.get("spatial_wet", 0.7)),
        "swarm_density": float(raw.get("swarm_density", 0.5)),
        "earth":         raw.get("earth"),
        "air":           raw.get("air"),
        "reverb":        raw.get("reverb"),
        "binaural":      raw.get("binaural"),
        "layers": [
            _normalize_layer_v1(l)
            for l in raw.get("layers", [])
            if l.get("enabled", True)
        ],
    }


def _from_v2(raw: dict) -> dict:
    meta    = raw.get("meta", {})
    glb     = raw.get("global", {})
    spatial = raw.get("spatial", {})

    return {
        "meta":          meta,
        "seed":          raw.get("seed"),
        "duration":      float(glb.get("duration_seconds", raw.get("duration", 60))),
        "spatial_depth": float(spatial.get("depth", 1.0)),
        "spatial_wet":   float(spatial.get("wetness", 0.7)),
        "swarm_density": float(spatial.get("swarm_density", 0.5)),
        "earth":         raw.get("earth"),
        "air":           raw.get("air"),
        "reverb":        raw.get("reverb"),
        "binaural":      raw.get("binaural"),
        "saturation":    float(raw.get("saturation", 0.3)),
        "layers": [
            _normalize_layer_v2(l)
            for l in raw.get("layers", [])
            if l.get("enabled", True)
        ],
    }


# ── validation ────────────────────────────────────────────────────────────────

_VALID_QUADRANTS    = {"front_left", "front_right", "rear_left", "rear_right", "center"}
_VALID_TRAJECTORIES = {"orbit", "pendulum", "drift", "spiral", "depth", "none"}

def _validate(preset: dict) -> None:
    errors = []

    if preset["duration"] <= 0:
        errors.append("duration must be > 0")

    if not preset["layers"]:
        errors.append("preset has no enabled layers")

    for i, layer in enumerate(preset["layers"]):
        label = f"layer {i} ({layer['name']!r})"

        # Skip FM-specific validation for granular layers
        if layer.get("type") == "granular":
            if layer["quadrant"] not in _VALID_QUADRANTS:
                errors.append(
                    f"{label}: quadrant {layer['quadrant']!r} not in {_VALID_QUADRANTS}"
                )
            if layer["trajectory_x"] not in _VALID_TRAJECTORIES:
                errors.append(f"{label}: unknown trajectory_x {layer['trajectory_x']!r}")
            if layer["trajectory_y"] not in _VALID_TRAJECTORIES:
                errors.append(f"{label}: unknown trajectory_y {layer['trajectory_y']!r}")
            continue

        if layer["root"] <= 0:
            errors.append(f"{label}: root must be > 0 (got {layer['root']})")
        if layer["voices"] < 1:
            errors.append(f"{label}: voices must be >= 1 (got {layer['voices']})")
        if not layer["ratios"]:
            errors.append(f"{label}: ratios list is empty")
        if not layer["fm_ratios"]:
            errors.append(f"{label}: fm_ratios list is empty")
        if layer["amp_min"] > layer["amp_max"]:
            errors.append(
                f"{label}: amp_min ({layer['amp_min']}) > amp_max ({layer['amp_max']})"
            )
        if layer["fm_index"] < 0:
            errors.append(f"{label}: fm_index must be >= 0")
        if layer["quadrant"] not in _VALID_QUADRANTS:
            errors.append(
                f"{label}: quadrant {layer['quadrant']!r} not in {_VALID_QUADRANTS}"
            )
        if layer["trajectory_x"] not in _VALID_TRAJECTORIES:
            errors.append(f"{label}: unknown trajectory_x {layer['trajectory_x']!r}")
        if layer["trajectory_y"] not in _VALID_TRAJECTORIES:
            errors.append(f"{label}: unknown trajectory_y {layer['trajectory_y']!r}")

    if errors:
        raise ValueError(
            "Preset validation failed:\n"
            + "\n".join(f"  • {e}" for e in errors)
        )


# ── public API ────────────────────────────────────────────────────────────────

def load_preset_from_yaml_string(yaml_text: str) -> dict:
    """
    Load and normalise a preset from a raw YAML string (e.g. uploaded by the user).
    Inheritance is NOT resolved (the file is standalone).
    Raises ValueError if the preset is structurally invalid.
    """
    raw = yaml.safe_load(yaml_text) or {}
    layers = raw.get("layers") or []
    is_v2 = bool(layers) and "synthesis" in layers[0]
    if is_v2 or "global" in raw:
        preset = _from_v2(raw)
    else:
        preset = _from_v1(raw)
    _validate(preset)
    return preset


def load_preset(path) -> dict:
    """
    Load and normalise a preset from *path* (.json or .yaml/.yml).
    Resolves inheritance chains before normalisation.
    Raises ValueError if the preset is structurally invalid.
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix in (".yaml", ".yml"):
        raw = _load_raw_yaml(path)
        # Resolve inheritance chain (deep-merges parent → child)
        raw = _resolve_inheritance(raw, path)
        # Detect v2 by checking the first layer for a 'synthesis' key
        layers = raw.get("layers") or []
        is_v2 = bool(layers) and "synthesis" in layers[0]
        if is_v2 or "global" in raw:
            preset = _from_v2(raw)
        else:
            preset = _from_v1(raw)
    else:
        with path.open(encoding="utf-8") as f:
            raw = json.load(f)
        preset = _from_v1(raw)

    _validate(preset)
    return preset
