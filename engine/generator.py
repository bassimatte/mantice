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
    },
}

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

        voices = min(random.randint(*profile["voice_range"]), 20)  # cap at 20 per layer
        ratios = random.choice(profile["ratios_pool"])
        fm_ratios = random.choice([[1.0], [1.0, 1.5], [1.0, 2.0], [1.0, 2.5, 3.0]])
        fm_index = random.uniform(*profile["fm_index_range"])
        drift = random.uniform(*profile["drift_range"])

        layer = {
            "name": _layer_name_for_freq(root, i),
            "enabled": True,
            "synthesis": {
                "root": round(root, 2),
                "voices": voices,
                "ratios": ratios,
            },
            "fm": {
                "ratios": fm_ratios,
                "index": round(fm_index, 3),
            },
            "dynamics": {
                "mix": round(random.uniform(0.4, 1.2), 2),
                "amp_min": round(random.uniform(0.002, 0.02), 4),
                "amp_max": round(random.uniform(0.03, 0.08), 4),
                "drift": round(drift, 4),
            },
            "spatial_motion": {
                "quadrant": random.choice(_QUADRANTS),
                "speed": round(random.uniform(0.002, 0.012), 4),
                "trajectory_x": random.choice(_TRAJECTORIES_X),
                "trajectory_y": random.choice(_TRAJECTORIES_Y),
            },
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
