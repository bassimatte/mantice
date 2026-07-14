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
import math
import warnings
from pathlib import Path
from typing import Optional

import yaml

from . import config

# ── volume helpers ────────────────────────────────────────────────────────────

def _mix_to_db(volume_db_raw, mix_fallback=1.0) -> float:
    """Convert old linear mix (0–1) → volume_db, or pass through existing volume_db."""
    if volume_db_raw is not None:
        return round(float(volume_db_raw), 1)
    mix = float(mix_fallback) if mix_fallback is not None else 1.0
    return round(20.0 * math.log10(max(mix, 1e-6)), 1)


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
    root = float(layer.get("root") or layer.get("root_hz", 110))
    return {
        "name":         layer.get("name", "Layer"),
        "muted":        bool(layer.get("muted", False)) or not bool(layer.get("enabled", True)),
        "type":          layer.get("type", "fm"),
        "root":         root,
        "tuning_degree": layer.get("tuning_degree", "unison"),
        "voices":       int(layer.get("voices", 4)),
        "ratios":       [float(r) for r in layer.get("ratios", [1.0])],
        "fm_ratios":    [float(r) for r in layer.get("fm_ratios", [1.0])],
        "fm_index":     float(layer.get("fm_index", 0.1)),
        "band":         layer.get("band", _infer_band(root)),
        "volume_db":    _mix_to_db(layer.get("volume_db"), layer.get("mix", 1.0)),
        "amp_min":      float(layer.get("amp_min", 0.001)),
        "amp_max":      float(layer.get("amp_max", 0.05)),
        "drift":        float(layer.get("drift", 0.01)),
        "quadrant":     layer.get("quadrant", "center"),
        "speed":        float(layer.get("speed", 0.01)),
        "trajectory_x": layer.get("trajectory_x", "none"),
        "trajectory_y": layer.get("trajectory_y", "none"),
        "pan":          {"center": 0.0, "left": -1.0, "right": 1.0}.get(
                            str(layer.get("pan", 0.0)).lower(),
                            float(layer.get("pan", 0.0))
                        ),
        "width":        float(layer.get("width", 1.0)),
        "spread":       float(layer.get("spread", 1.0)),
        "blend":        float(layer.get("blend", 1.0)),
        # FM texture
        "harmonics":       int(layer.get("harmonics", 4)),
        "harmonic_decay":  float(layer.get("harmonic_decay", 0.7)),
        "noise_amount":    float(layer.get("noise_amount", 0.0)),
        "noise_color":     layer.get("noise_color", "pink"),
        # Elevation and chorus
        "elevation":        float(layer.get("elevation", 0.0)),
        "elevation_motion": layer.get("elevation_motion", "static"),
        "elevation_speed":  float(layer.get("elevation_speed", 0.1)),
        "elevation_range":  float(layer.get("elevation_range", 60.0)),
        "chorus_rate":      float(layer.get("chorus_rate", 0.5)),
        "chorus_depth":     float(layer.get("chorus_depth", 0.005)),
        "chorus_mix":       float(layer.get("chorus_mix", 0.0)),
        "chorus_voices":    int(layer.get("chorus_voices", 2)),
        # Filter and LFO
        "filter_type":      layer.get("filter_type", "off"),
        "filter_cutoff":    float(layer.get("filter_cutoff", 2000)),
        "filter_resonance": float(layer.get("filter_resonance", 1.0)),
        "filter_lfo_rate":  float(layer.get("filter_lfo_rate", 0.1)),
        "filter_lfo_depth": float(layer.get("filter_lfo_depth", 0.0)),
        "filter_lfo_shape": layer.get("filter_lfo_shape", "sine"),
        "filter_vowel":     layer.get("filter_vowel", "a"),
        # Subtractive
        "waveform":     layer.get("waveform", "saw"),
        "detune_cents": float(layer.get("detune_cents", 8.0)),
        "sub_mix":      float(layer.get("sub_mix", 0.3)),
        # Granular
        "source":          layer.get("source", "singing_bowl.ogg"),
        "grain_size":      float(layer.get("grain_size", 80)),
        "density":         float(layer.get("density", 15)),
        "pitch_spread":    float(layer.get("pitch_spread", 0.3)),
        "position":        float(layer.get("position", 0.5)),
        "scatter":         float(layer.get("scatter", 0.5)),
        "envelope":        layer.get("envelope", "hann"),
        "position_mode":   layer.get("position_mode", "linear"),
        "position_chaos":  float(layer.get("position_chaos", 0.3)),
        "pitch_mode":      layer.get("pitch_mode", "resample"),
        "pitch_semitones": float(layer.get("pitch_semitones", 0.0)),
        "sample_root_hz":  layer.get("sample_root_hz"),
        "stereo_width":    float(layer.get("stereo_width", 0.8)),
        # Wavetable
        "wavetable_source":       layer.get("wavetable_source", ""),
        "wavetable_frame_size":   int(layer.get("wavetable_frame_size", 2048)),
        "wavetable_position":     float(layer.get("wavetable_position", 0.0)),
        "wavetable_scan_start":   float(layer.get("wavetable_scan_start", 0.0)),
        "wavetable_scan_end":     float(layer.get("wavetable_scan_end", 1.0)),
        "wavetable_scan_rate":    float(layer.get("wavetable_scan_rate", 0.01)),
        "wavetable_scan_mode":    layer.get("wavetable_scan_mode", "pingpong"),
        "wavetable_detune_cents": float(layer.get("wavetable_detune_cents", 7.0)),
        "wavetable_name":         layer.get("wavetable_name", ""),
        "wavetable_sha256":       layer.get("wavetable_sha256", ""),
        "wavetable_source_url":   layer.get("wavetable_source_url", ""),
        "wavetable_creator":      layer.get("wavetable_creator", ""),
        "wavetable_license":      layer.get("wavetable_license", ""),
        # Distortion
        "distortion_drive": float(layer.get("distortion_drive", 0.0)),
        "distortion_type":  layer.get("distortion_type", "soft"),
        # V24 per-layer flanger & phaser
        "flanger_wet":       float(layer.get("flanger_wet", 0.0)),
        "flanger_rate":      float(layer.get("flanger_rate", 0.25)),
        "flanger_depth":     float(layer.get("flanger_depth", 0.5)),
        "flanger_feedback":  float(layer.get("flanger_feedback", 0.4)),
        "phaser_wet":        float(layer.get("phaser_wet", 0.0)),
        "phaser_rate":       float(layer.get("phaser_rate", 0.5)),
        "phaser_depth":      float(layer.get("phaser_depth", 0.7)),
        "phaser_center_hz":  float(layer.get("phaser_center_hz", 800.0)),
        "phaser_feedback":   float(layer.get("phaser_feedback", 0.0)),
        "phaser_stages":     int(layer.get("phaser_stages", 4)),
        # V26 parameter automation
        "automation":        layer.get("automation") or {},
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
        "muted":        bool(layer.get("muted", False)) or not bool(layer.get("enabled", True)),
        "type":         layer_type,
        # FM synthesis keys (used when type == "fm")
        "root":         root,
        "tuning_degree": layer.get("tuning_degree", "unison"),
        "voices":       int(synth.get("voices", 8)),
        "ratios":       [float(r) for r in synth.get("ratios", [1.0])],
        "fm_ratios":    [float(r) for r in fm.get("ratios", [1.0])],
        "fm_index":     float(fm.get("index", 0.1)),
        "band":         layer.get("band", _infer_band(root)),
        "volume_db":    _mix_to_db(layer.get("volume_db"), dyn.get("mix", 1.0)),
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
        "filter_vowel":     layer.get("filter_vowel", "a"),
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
        "position_mode": layer.get("position_mode", "linear"),
        "position_chaos": float(layer.get("position_chaos", 0.3)),
        "pitch_mode": layer.get("pitch_mode", "resample"),
        "pitch_semitones": float(layer.get("pitch_semitones", 0.0)),
        "sample_root_hz": layer.get("sample_root_hz"),
        "stereo_width": float(layer.get("stereo_width", 0.8)),
        # V27 wavetable keys
        "wavetable_source": layer.get("wavetable_source", ""),
        "wavetable_frame_size": int(layer.get("wavetable_frame_size", 2048)),
        "wavetable_position": float(layer.get("wavetable_position", 0.0)),
        "wavetable_scan_start": float(layer.get("wavetable_scan_start", 0.0)),
        "wavetable_scan_end": float(layer.get("wavetable_scan_end", 1.0)),
        "wavetable_scan_rate": float(layer.get("wavetable_scan_rate", 0.01)),
        "wavetable_scan_mode": layer.get("wavetable_scan_mode", "pingpong"),
        "wavetable_detune_cents": float(layer.get("wavetable_detune_cents", 7.0)),
        "wavetable_name": layer.get("wavetable_name", ""),
        "wavetable_sha256": layer.get("wavetable_sha256", ""),
        "wavetable_source_url": layer.get("wavetable_source_url", ""),
        "wavetable_creator": layer.get("wavetable_creator", ""),
        "wavetable_license": layer.get("wavetable_license", ""),
        # V22 pan & width
        "pan":   float(layer.get("pan", 0.0)),
        "width": float(layer.get("width", 1.0)),
        # V23 voice spread & blend (FM only)
        "spread": float(layer.get("spread", 1.0)),
        "blend":  float(layer.get("blend", 1.0)),
        # V24 per-layer flanger & phaser
        "flanger_wet":       float(layer.get("flanger_wet", 0.0)),
        "flanger_rate":      float(layer.get("flanger_rate", 0.25)),
        "flanger_depth":     float(layer.get("flanger_depth", 0.5)),
        "flanger_feedback":  float(layer.get("flanger_feedback", 0.4)),
        "phaser_wet":        float(layer.get("phaser_wet", 0.0)),
        "phaser_rate":       float(layer.get("phaser_rate", 0.5)),
        "phaser_depth":      float(layer.get("phaser_depth", 0.7)),
        "phaser_center_hz":  float(layer.get("phaser_center_hz", 800.0)),
        "phaser_feedback":   float(layer.get("phaser_feedback", 0.0)),
        "phaser_stages":     int(layer.get("phaser_stages", 4)),
        "distortion_drive":  float(layer.get("distortion_drive", 0.0)),
        "distortion_type":   layer.get("distortion_type", "soft"),
        # V26 parameter automation
        "automation":        layer.get("automation") or {},
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
        "saturation":    float(raw.get("saturation", 0.3)),
        "tuning_mode":   raw.get("tuning_mode", "free"),
        "tonic_hz":      float(raw.get("tonic_hz", 432.0)),
        "tuning_system_ji": raw.get("tuning_system_ji", "5limit_ji"),
        "pure_mode":     bool(raw.get("pure_mode", False)),
        "tuning_ref_a4": float(raw.get("tuning_ref_a4", 440.0)),
        "earth":         raw.get("earth"),
        "air":           raw.get("air"),
        "reverb":        raw.get("reverb"),
        "binaural":      raw.get("binaural"),
        "flanger":       raw.get("flanger"),
        "shimmer":       raw.get("shimmer"),
        "master":        raw.get("master"),
        "automation":    raw.get("automation") or {},
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
        "flanger":       raw.get("flanger"),
        "shimmer":       raw.get("shimmer"),
        "master":        raw.get("master"),
        "saturation":    float(raw.get("saturation", 0.3)),
        "automation":    raw.get("automation") or {},
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

        if layer.get("type") == "wavetable":
            if not layer.get("wavetable_source"):
                errors.append(f"{label}: wavetable_source is required")
            if layer.get("wavetable_frame_size", 0) < 32:
                errors.append(f"{label}: wavetable_frame_size must be >= 32")
            if layer.get("wavetable_scan_mode") not in {"static", "forward", "pingpong"}:
                errors.append(f"{label}: unknown wavetable_scan_mode {layer.get('wavetable_scan_mode')!r}")

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
