"""
engine/generator.py
-------------------
Random preset generator and mutation engine.

Features:
  - Generate fully random presets, optionally biased by mood
  - Mutate existing presets with controllable variation amount
  - Output valid YAML presets into presets/generated/
"""

import random
import math
from datetime import datetime
from pathlib import Path
from typing import Optional, List

import yaml


# ── Mood profiles ─────────────────────────────────────────────────────────────
# Each mood biases the random distributions toward a sonic character.

_MOOD_PROFILES = {
    "dark": {
        "root_range": (20, 110),
        "voice_range": (8, 40),
        "fm_index_range": (0.2, 1.2),
        "drift_range": (0.01, 0.04),
        "ratios_pool": [[1.0, 1.5], [1.0, 1.5, 2.0], [0.5, 1.0, 1.5, 2.5]],
        "reverb_decay": (0.90, 0.97),
        "reverb_damping": (0.5, 0.8),
        "reverb_room": (0.6, 1.0),
        "earth_prob": 0.7,
        "air_prob": 0.3,
        "mood_tags": ["dark", "ominous", "deep"],
        # layer type weights: [fm, subtractive, granular]
        "layer_type_weights": [45, 45, 10],
        # subtractive bias for this mood
        "sub_waveforms": ["saw", "square"],
        "sub_detune_range": (12.0, 28.0),
        "sub_mix_range": (0.35, 0.65),
        "sub_filter_types": ["lp", "lp", "bp"],
        "sub_cutoff_range": (200.0, 700.0),
        "sub_resonance_range": (1.8, 3.5),
        "sub_lfo_rate_range": (0.04, 0.15),
        "sub_lfo_depth_range": (0.4, 0.8),
        "sub_lfo_shapes": ["sine", "triangle"],
    },
    "bright": {
        "root_range": (440, 3000),
        "voice_range": (4, 20),
        "fm_index_range": (0.05, 0.4),
        "drift_range": (0.002, 0.01),
        "ratios_pool": [[1.0, 2.0, 3.0, 5.0], [1.0, 2.0, 4.0], [1.0, 3.0, 5.0, 7.0]],
        "reverb_decay": (0.80, 0.92),
        "reverb_damping": (0.1, 0.3),
        "reverb_room": (0.4, 0.8),
        "earth_prob": 0.1,
        "air_prob": 0.4,
        "mood_tags": ["bright", "shimmering", "ethereal"],
        "layer_type_weights": [60, 15, 25],
        "sub_waveforms": ["triangle", "saw"],
        "sub_detune_range": (4.0, 12.0),
        "sub_mix_range": (0.15, 0.4),
        "sub_filter_types": ["bp", "hp"],
        "sub_cutoff_range": (1500.0, 4000.0),
        "sub_resonance_range": (1.2, 2.5),
        "sub_lfo_rate_range": (0.2, 0.5),
        "sub_lfo_depth_range": (0.2, 0.5),
        "sub_lfo_shapes": ["sine", "sine", "triangle"],
    },
    "cinematic": {
        "root_range": (40, 440),
        "voice_range": (20, 80),
        "fm_index_range": (0.05, 0.3),
        "drift_range": (0.005, 0.02),
        "ratios_pool": [[1.0, 2.0, 3.0], [0.5, 1.0, 2.0, 3.0, 4.0], [1.0, 1.5, 2.0, 3.0]],
        "reverb_decay": (0.88, 0.95),
        "reverb_damping": (0.3, 0.5),
        "reverb_room": (0.7, 1.0),
        "earth_prob": 0.6,
        "air_prob": 0.5,
        "mood_tags": ["cinematic", "epic", "immersive"],
        "layer_type_weights": [50, 35, 15],
        "sub_waveforms": ["saw", "triangle"],
        "sub_detune_range": (8.0, 22.0),
        "sub_mix_range": (0.4, 0.9),
        "sub_filter_types": ["lp", "lp", "bp"],
        "sub_cutoff_range": (400.0, 1200.0),
        "sub_resonance_range": (1.5, 3.0),
        "sub_lfo_rate_range": (0.04, 0.12),
        "sub_lfo_depth_range": (0.3, 0.7),
        "sub_lfo_shapes": ["sine", "triangle"],
    },
    "minimal": {
        "root_range": (60, 220),
        "voice_range": (2, 6),
        "fm_index_range": (0.0, 0.05),
        "drift_range": (0.001, 0.005),
        "ratios_pool": [[1.0], [1.0, 2.0], [1.0, 1.5]],
        "reverb_decay": (0.85, 0.92),
        "reverb_damping": (0.2, 0.4),
        "reverb_room": (0.3, 0.6),
        "earth_prob": 0.2,
        "air_prob": 0.1,
        "mood_tags": ["minimal", "pure", "meditative"],
        "layer_type_weights": [65, 20, 15],
        "sub_waveforms": ["triangle", "saw"],
        "sub_detune_range": (3.0, 8.0),
        "sub_mix_range": (0.3, 0.6),
        "sub_filter_types": ["lp", "off"],
        "sub_cutoff_range": (600.0, 1800.0),
        "sub_resonance_range": (0.8, 1.5),
        "sub_lfo_rate_range": (0.02, 0.08),
        "sub_lfo_depth_range": (0.1, 0.35),
        "sub_lfo_shapes": ["sine"],
    },
    "industrial": {
        "root_range": (50, 300),
        "voice_range": (10, 50),
        "fm_index_range": (0.5, 2.0),
        "drift_range": (0.02, 0.06),
        "ratios_pool": [[1.0, 1.41, 2.0], [1.0, 1.7, 2.3], [0.5, 1.0, 1.33, 2.67]],
        "reverb_decay": (0.75, 0.88),
        "reverb_damping": (0.3, 0.6),
        "reverb_room": (0.3, 0.7),
        "earth_prob": 0.4,
        "air_prob": 0.6,
        "mood_tags": ["industrial", "metallic", "harsh"],
        "layer_type_weights": [35, 55, 10],
        "sub_waveforms": ["saw", "square", "square"],
        "sub_detune_range": (15.0, 35.0),
        "sub_mix_range": (0.5, 1.0),
        "sub_filter_types": ["lp", "bp", "hp"],
        "sub_cutoff_range": (300.0, 2000.0),
        "sub_resonance_range": (2.0, 4.5),
        "sub_lfo_rate_range": (0.1, 0.4),
        "sub_lfo_depth_range": (0.3, 0.7),
        "sub_lfo_shapes": ["square", "triangle", "sine"],
    },
    "nature": {
        "root_range": (80, 400),
        "voice_range": (8, 30),
        "fm_index_range": (0.02, 0.15),
        "drift_range": (0.008, 0.025),
        "ratios_pool": [[1.0, 2.0, 3.0], [1.0, 1.5, 2.0], [0.5, 1.0, 2.0]],
        "reverb_decay": (0.82, 0.90),
        "reverb_damping": (0.3, 0.5),
        "reverb_room": (0.5, 0.9),
        "earth_prob": 0.5,
        "air_prob": 0.8,
        "mood_tags": ["organic", "natural", "earthy"],
        "layer_type_weights": [40, 20, 40],
        "sub_waveforms": ["triangle", "saw"],
        "sub_detune_range": (5.0, 15.0),
        "sub_mix_range": (0.2, 0.5),
        "sub_filter_types": ["lp", "bp"],
        "sub_cutoff_range": (500.0, 2000.0),
        "sub_resonance_range": (1.0, 2.0),
        "sub_lfo_rate_range": (0.08, 0.25),
        "sub_lfo_depth_range": (0.2, 0.5),
        "sub_lfo_shapes": ["sine", "triangle"],
    },
    "chaotic": {
        "root_range": (30, 2000),
        "voice_range": (40, 120),
        "fm_index_range": (0.3, 1.5),
        "drift_range": (0.03, 0.08),
        "ratios_pool": [[1.0, 1.17, 1.83, 2.41], [0.5, 1.0, 1.61, 2.72], [1.0, 1.33, 1.87, 3.14]],
        "reverb_decay": (0.85, 0.95),
        "reverb_damping": (0.2, 0.5),
        "reverb_room": (0.5, 1.0),
        "earth_prob": 0.5,
        "air_prob": 0.7,
        "mood_tags": ["chaotic", "dense", "unpredictable"],
        "layer_type_weights": [40, 35, 25],
        "sub_waveforms": ["saw", "square", "triangle"],
        "sub_detune_range": (10.0, 40.0),
        "sub_mix_range": (0.3, 0.9),
        "sub_filter_types": ["lp", "bp", "hp"],
        "sub_cutoff_range": (200.0, 3000.0),
        "sub_resonance_range": (1.5, 5.0),
        "sub_lfo_rate_range": (0.05, 0.6),
        "sub_lfo_depth_range": (0.2, 0.9),
        "sub_lfo_shapes": ["sine", "triangle", "square"],
    },
}

# Granular sample pool (files that exist in engine/samples/)
_GRANULAR_SAMPLES = [
    "singing_bowl.ogg",
    "tibetan_bowl.ogg",
    "gong.ogg",
    "metal_hit.ogg",
]

_QUADRANTS = ["front_left", "front_right", "rear_left", "rear_right", "center"]
_TRAJECTORIES_X = ["orbit", "pendulum", "drift", "spiral", "none"]
_TRAJECTORIES_Y = ["depth", "none"]

_NAME_PARTS_A = [
    "Ancient", "Frozen", "Burning", "Infinite", "Hollow", "Crystal", "Iron",
    "Solar", "Lunar", "Void", "Phantom", "Tectonic", "Spectral", "Magnetic",
    "Obsidian", "Amber", "Molten", "Silent", "Fractal", "Orbital",
]
_NAME_PARTS_B = [
    "Resonance", "Cathedral", "Monolith", "Engine", "Drift", "Pulse", "Choir",
    "Chamber", "Expanse", "Vortex", "Field", "Machine", "Horizon", "Abyss",
    "Frequency", "Pressure", "Continuum", "Whisper", "Storm", "Membrane",
]


def _random_name() -> str:
    return f"{random.choice(_NAME_PARTS_A)} {random.choice(_NAME_PARTS_B)}"


def _clamp(val, lo, hi):
    return max(lo, min(hi, val))


def _layer_name_for_freq(root_hz: float, index: int) -> str:
    """Generate a descriptive layer name based on frequency range."""
    _DESCRIPTORS = {
        "sub": ["Sub Rumble", "Earth Pulse", "Deep Fundament", "Tectonic Bass", "Infra Drone"],
        "bass": ["Low Drone", "Bass Foundation", "Dark Current", "Deep Hum", "Gravity Well"],
        "low_mid": ["Warm Body", "Mid Resonance", "Core Tone", "Amber Field", "Dense Texture"],
        "mid": ["Harmonic Bed", "Mid Shimmer", "Tonal Weave", "Spectral Body", "Presence Layer"],
        "high_mid": ["Bright Overtone", "Crystal Lattice", "Upper Harmonic", "Luminous Ring", "Air Texture"],
        "high": ["High Shimmer", "Celestial Dust", "Ether Whisper", "Glass Resonance", "Ice Particles"],
    }
    if root_hz < 50:
        band = "sub"
    elif root_hz < 120:
        band = "bass"
    elif root_hz < 300:
        band = "low_mid"
    elif root_hz < 800:
        band = "mid"
    elif root_hz < 2000:
        band = "high_mid"
    else:
        band = "high"
    names = _DESCRIPTORS[band]
    return names[index % len(names)]


def _compute_cost(layers: list) -> float:
    """Compute streaming cost metric for a list of layers."""
    total = 0.0
    for l in layers:
        if not l.get("enabled", True):
            continue
        v = l.get("synthesis", {}).get("voices", 8)
        h = l.get("harmonics", 4)
        fm_idx = l.get("fm", {}).get("index", 0.1)
        fm_weight = 1.0 + fm_idx * 0.5
        total += v * h * fm_weight
    return total


def _cap_preset_cost(preset: dict, max_cost: float = 500) -> None:
    """Reduce voices on layers until total cost is within budget."""
    layers = preset.get("layers", [])
    while _compute_cost(layers) > max_cost:
        # Find the most expensive layer and reduce its voices
        worst_idx = -1
        worst_cost = 0
        for i, l in enumerate(layers):
            if not l.get("enabled", True):
                continue
            v = l.get("synthesis", {}).get("voices", 8)
            h = l.get("harmonics", 4)
            fm_idx = l.get("fm", {}).get("index", 0.1)
            cost = v * h * (1.0 + fm_idx * 0.5)
            if cost > worst_cost:
                worst_cost = cost
                worst_idx = i
        if worst_idx < 0:
            break
        current_v = layers[worst_idx].get("synthesis", {}).get("voices", 8)
        if current_v <= 2:
            break  # can't reduce further
        layers[worst_idx]["synthesis"]["voices"] = max(2, current_v - 2)


# ── Generator ─────────────────────────────────────────────────────────────────

def generate_preset(mood: Optional[str] = None, seed: Optional[int] = None) -> dict:
    """
    Generate a fully random preset, optionally biased by mood.
    Returns a raw dict ready to be saved as YAML.
    """
    if seed is not None:
        random.seed(seed)

    # Select mood profile or use neutral defaults
    if mood and mood in _MOOD_PROFILES:
        profile = _MOOD_PROFILES[mood]
    else:
        # Neutral: pick a random mood as base for variety
        profile = random.choice(list(_MOOD_PROFILES.values()))
        mood = "mixed"

    name = _random_name()
    slug = name.lower().replace(" ", "_")

    # Duration
    duration = random.choice([60, 90, 120, 150, 180])

    # Number of layers
    n_layers = random.choices([1, 2, 3, 4, 5], weights=[5, 30, 35, 20, 10])[0]

    layers = []
    for i in range(n_layers):
        root = random.uniform(*profile["root_range"])
        # Quantize to nearest semitone for musicality
        root = 440 * (2 ** (round(12 * math.log2(root / 440)) / 12))

        # Pick layer type using mood-biased weights
        layer_type = random.choices(
            ["fm", "subtractive", "granular"],
            weights=profile["layer_type_weights"],
        )[0]

        voices = min(random.randint(*profile["voice_range"]), 20)  # cap at 20 per layer
        ratios = random.choice(profile["ratios_pool"])
        drift = random.uniform(*profile["drift_range"])

        spatial = {
            "quadrant": random.choice(_QUADRANTS),
            "speed": round(random.uniform(0.002, 0.012), 4),
            "trajectory_x": random.choice(_TRAJECTORIES_X),
            "trajectory_y": random.choice(_TRAJECTORIES_Y),
        }
        dynamics = {
            "mix": round(random.uniform(0.4, 1.2), 2),
            "amp_min": round(random.uniform(0.002, 0.02), 4),
            "amp_max": round(random.uniform(0.03, 0.08), 4),
            "drift": round(drift, 4),
        }

        if layer_type == "subtractive":
            layer = {
                "name": _layer_name_for_freq(root, i),
                "enabled": True,
                "type": "subtractive",
                "synthesis": {
                    "root": round(root, 2),
                    "voices": min(voices, 8),
                    "ratios": ratios,
                },
                "fm": {"ratios": [1.0], "index": 0.0},
                "dynamics": dynamics,
                "spatial_motion": spatial,
                "waveform": random.choice(profile["sub_waveforms"]),
                "detune_cents": round(random.uniform(*profile["sub_detune_range"]), 1),
                "sub_mix": round(random.uniform(*profile["sub_mix_range"]), 2),
                "filter_type": random.choice(profile["sub_filter_types"]),
                "filter_cutoff": round(random.uniform(*profile["sub_cutoff_range"]), 1),
                "filter_resonance": round(random.uniform(*profile["sub_resonance_range"]), 2),
                "filter_lfo_rate": round(random.uniform(*profile["sub_lfo_rate_range"]), 3),
                "filter_lfo_depth": round(random.uniform(*profile["sub_lfo_depth_range"]), 2),
                "filter_lfo_shape": random.choice(profile["sub_lfo_shapes"]),
                "chorus_rate": round(random.uniform(0.2, 0.8), 2),
                "chorus_depth": round(random.uniform(0.004, 0.015), 4),
                "chorus_mix": round(random.uniform(0.1, 0.5), 2),
                "chorus_voices": random.choice([2, 3]),
            }
        elif layer_type == "granular":
            layer = {
                "name": _layer_name_for_freq(root, i),
                "enabled": True,
                "type": "granular",
                "source": random.choice(_GRANULAR_SAMPLES),
                "grain_size": round(random.uniform(40, 200), 1),
                "density": round(random.uniform(8, 30), 1),
                "pitch_spread": round(random.uniform(0.1, 0.6), 2),
                "position": round(random.uniform(0.1, 0.9), 2),
                "scatter": round(random.uniform(0.2, 0.8), 2),
                "envelope": random.choice(["hann", "triangle", "trapezoid"]),
                "synthesis": {"root": round(root, 2), "voices": voices, "ratios": ratios},
                "fm": {"ratios": [1.0], "index": 0.0},
                "dynamics": dynamics,
                "spatial_motion": spatial,
                "filter_type": random.choice(["off", "lp", "bp"]),
                "filter_cutoff": round(random.uniform(500.0, 3000.0), 1),
                "filter_resonance": round(random.uniform(0.7, 2.0), 2),
                "filter_lfo_rate": round(random.uniform(0.05, 0.3), 3),
                "filter_lfo_depth": round(random.uniform(0.0, 0.4), 2),
                "filter_lfo_shape": random.choice(["sine", "triangle"]),
                "chorus_rate": round(random.uniform(0.3, 0.7), 2),
                "chorus_depth": round(random.uniform(0.003, 0.01), 4),
                "chorus_mix": round(random.uniform(0.0, 0.3), 2),
                "chorus_voices": 2,
            }
        else:  # fm
            fm_ratios = random.choice([[1.0], [1.0, 1.5], [1.0, 2.0], [1.0, 2.5, 3.0]])
            fm_index = random.uniform(*profile["fm_index_range"])
            layer = {
                "name": _layer_name_for_freq(root, i),
                "enabled": True,
                "type": "fm",
                "synthesis": {
                    "root": round(root, 2),
                    "voices": voices,
                    "ratios": ratios,
                },
                "fm": {
                    "ratios": fm_ratios,
                    "index": round(fm_index, 3),
                },
                "dynamics": dynamics,
                "spatial_motion": spatial,
                "filter_type": random.choice(["off", "off", "lp", "hp"]),
                "filter_cutoff": round(random.uniform(400.0, 4000.0), 1),
                "filter_resonance": round(random.uniform(0.7, 2.0), 2),
                "filter_lfo_rate": round(random.uniform(0.05, 0.2), 3),
                "filter_lfo_depth": round(random.uniform(0.0, 0.3), 2),
                "filter_lfo_shape": random.choice(["sine", "triangle"]),
                "chorus_rate": round(random.uniform(0.3, 0.8), 2),
                "chorus_depth": round(random.uniform(0.003, 0.01), 4),
                "chorus_mix": round(random.uniform(0.0, 0.35), 2),
                "chorus_voices": random.choice([2, 3]),
            }
        layers.append(layer)

    # Reverb
    reverb = {
        "enabled": True,
        "room_size": round(random.uniform(*profile["reverb_room"]), 2),
        "decay": round(random.uniform(*profile["reverb_decay"]), 2),
        "damping": round(random.uniform(*profile["reverb_damping"]), 2),
        "modulation": round(random.uniform(0.1, 0.5), 2),
        "wet": round(random.uniform(0.2, 0.55), 2),
        "predelay": round(random.uniform(0.01, 0.06), 3),
    }

    # Earth
    earth = None
    if random.random() < profile["earth_prob"]:
        earth = {
            "enabled": True,
            "tectonic_frequency": random.randint(12, 24),
            "pressure": round(random.uniform(0.15, 0.5), 2),
            "movement": round(random.uniform(0.005, 0.03), 3),
        }

    # Air
    air = None
    if random.random() < profile["air_prob"]:
        air = {
            "enabled": True,
            "intensity": round(random.uniform(0.05, 0.3), 2),
            "movement": round(random.uniform(0.004, 0.015), 4),
            "turbulence": round(random.uniform(0.02, 0.12), 3),
        }

    preset = {
        "meta": {
            "name": name,
            "slug": slug,
            "category": "generated",
            "mood": profile["mood_tags"],
            "description": f"Auto-generated {mood} drone preset.",
            "author": "MANTICE Generator",
            "origin": "generated",
        },
        "global": {
            "duration_seconds": duration,
            "sample_rate": 48000,
            "bit_depth": "24-bit",
        },
        "reverb": reverb,
        "spatial": {
            "depth": round(random.uniform(1.0, 3.0), 1),
            "wetness": 0.0,
            "swarm_density": round(random.uniform(0.2, 0.7), 2),
        },
        "layers": layers,
    }

    if earth:
        preset["earth"] = earth
    if air:
        preset["air"] = air

    # ── Cost cap: ensure preset streams smoothly (max cost 500) ───────────
    _cap_preset_cost(preset, max_cost=500)

    return preset


# ── Mutator ───────────────────────────────────────────────────────────────────

def mutate_preset(preset: dict, amount: float = 0.3, seed: Optional[int] = None) -> dict:
    """
    Create a mutated variation of an existing preset.
    amount: 0.0 = identical, 1.0 = wild variation.
    Returns a new raw dict (does not modify the input).
    """
    import copy
    if seed is not None:
        random.seed(seed)

    amount = _clamp(amount, 0.0, 1.0)
    result = copy.deepcopy(preset)

    # Mutate meta
    original_name = result.get("meta", {}).get("name", "Unknown")
    result.setdefault("meta", {})
    result["meta"]["name"] = f"{original_name} (mutated)"
    result["meta"]["slug"] = result["meta"].get("slug", "mutated") + "_mutated"
    result["meta"]["origin"] = f"mutated from {original_name}"
    result["meta"]["category"] = "generated"

    # Helper: perturb a numeric value
    def perturb(val, lo, hi, scale=1.0):
        noise = random.gauss(0, amount * scale * (hi - lo) * 0.3)
        return _clamp(val + noise, lo, hi)

    # Mutate global duration
    glb = result.get("global", {})
    if "duration_seconds" in glb:
        glb["duration_seconds"] = int(perturb(glb["duration_seconds"], 30, 300))

    # Mutate reverb
    reverb = result.get("reverb")
    if reverb and isinstance(reverb, dict):
        if "room_size" in reverb:
            reverb["room_size"] = round(perturb(reverb["room_size"], 0.1, 1.0), 2)
        if "decay" in reverb:
            reverb["decay"] = round(perturb(reverb["decay"], 0.5, 0.99), 2)
        if "damping" in reverb:
            reverb["damping"] = round(perturb(reverb["damping"], 0.0, 0.9), 2)
        if "wet" in reverb:
            reverb["wet"] = round(perturb(reverb["wet"], 0.1, 0.7), 2)

    # Mutate earth
    earth = result.get("earth")
    if earth and isinstance(earth, dict):
        if "tectonic_frequency" in earth:
            earth["tectonic_frequency"] = int(perturb(earth["tectonic_frequency"], 10, 30))
        if "pressure" in earth:
            earth["pressure"] = round(perturb(earth["pressure"], 0.1, 0.6), 2)

    # Mutate air
    air = result.get("air")
    if air and isinstance(air, dict):
        if "intensity" in air:
            air["intensity"] = round(perturb(air["intensity"], 0.02, 0.4), 2)
        if "turbulence" in air:
            air["turbulence"] = round(perturb(air["turbulence"], 0.01, 0.15), 3)

    # Mutate layers
    layers = result.get("layers", [])
    for layer in layers:
        synth = layer.get("synthesis", {})
        fm = layer.get("fm", {})
        dyn = layer.get("dynamics", {})
        spm = layer.get("spatial_motion", {})

        # Root: perturb by semitones
        if "root" in synth:
            semitone_shift = random.gauss(0, amount * 4)
            synth["root"] = round(synth["root"] * (2 ** (semitone_shift / 12)), 2)
            synth["root"] = _clamp(synth["root"], 16, 8000)

        # Voices
        if "voices" in synth:
            synth["voices"] = int(_clamp(
                synth["voices"] + random.gauss(0, amount * synth["voices"] * 0.3),
                2, 150
            ))

        # FM index
        if "index" in fm:
            fm["index"] = round(perturb(fm["index"], 0.0, 2.0), 3)

        # Dynamics
        if "drift" in dyn:
            dyn["drift"] = round(perturb(dyn["drift"], 0.001, 0.08), 4)
        if "mix" in dyn:
            dyn["mix"] = round(perturb(dyn["mix"], 0.2, 1.5), 2)

        # Spatial: chance to reassign quadrant at high amount
        if random.random() < amount * 0.4:
            spm["quadrant"] = random.choice(_QUADRANTS)
        if random.random() < amount * 0.3:
            spm["trajectory_x"] = random.choice(_TRAJECTORIES_X)

        # Speed
        if "speed" in spm:
            spm["speed"] = round(perturb(spm["speed"], 0.001, 0.02), 4)

    # At high amount, chance to add/remove a layer
    if amount > 0.6 and len(layers) > 1 and random.random() < amount * 0.3:
        layers.pop(random.randint(0, len(layers) - 1))
    elif amount > 0.5 and len(layers) < 5 and random.random() < amount * 0.2:
        # Duplicate a random layer with mutation
        donor = copy.deepcopy(random.choice(layers))
        root_hz = donor.get("synthesis", donor.get("root", 100))
        if isinstance(root_hz, dict):
            root_hz = root_hz.get("root", 100)
        donor["name"] = _layer_name_for_freq(float(root_hz), len(layers))
        layers.append(donor)

    result["layers"] = layers
    _cap_preset_cost(result, max_cost=500)
    return result


# ── File I/O ──────────────────────────────────────────────────────────────────

def save_generated_preset(preset: dict, output_dir: Path) -> Path:
    """Save a generated preset as YAML. Returns the file path."""
    output_dir.mkdir(parents=True, exist_ok=True)

    slug = preset.get("meta", {}).get("slug", "preset")
    # Ensure unique filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{slug}_{timestamp}.yaml"
    path = output_dir / filename

    # Avoid collision
    counter = 1
    while path.exists():
        filename = f"{slug}_{timestamp}_{counter}.yaml"
        path = output_dir / filename
        counter += 1

    with path.open("w", encoding="utf-8") as f:
        yaml.dump(preset, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return path


def get_available_moods() -> List[str]:
    """Return list of available mood presets."""
    return sorted(_MOOD_PROFILES.keys())
