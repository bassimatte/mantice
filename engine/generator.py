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
}

# Expressive generator intent (0 = left-hand label, 1 = right-hand label).
# Mood buttons provide useful starting points; callers may override any axis.
_MOOD_INTENTS = {
    "dark":       dict(density=.62, motion=.35, space=.78, tonality=.62, weight=.90, stability=.58, brightness=.15, evolution=.72),
    "bright":     dict(density=.45, motion=.48, space=.68, tonality=.82, weight=.18, stability=.72, brightness=.92, evolution=.60),
    "cinematic":  dict(density=.82, motion=.65, space=.95, tonality=.72, weight=.76, stability=.62, brightness=.62, evolution=.92),
    "minimal":    dict(density=.12, motion=.15, space=.35, tonality=.92, weight=.42, stability=.92, brightness=.46, evolution=.22),
    "industrial": dict(density=.75, motion=.88, space=.45, tonality=.22, weight=.82, stability=.18, brightness=.55, evolution=.68),
    "nature":     dict(density=.48, motion=.68, space=.72, tonality=.55, weight=.45, stability=.42, brightness=.58, evolution=.88),
    "mixed":      dict(density=.50, motion=.50, space=.50, tonality=.50, weight=.50, stability=.50, brightness=.50, evolution=.50),
}

_QUADRANTS = ["front_left", "front_right", "rear_left", "rear_right", "center"]
_TRAJECTORIES_X = ["orbit", "pendulum", "drift", "spiral", "none"]
_TRAJECTORIES_Y = ["depth", "none"]

# Streaming safety caps — keep real-time preview responsive
_MAX_LAYERS = 3
_MAX_VOICES_FM = 12          # FM: each voice is one oscillator pair
_MAX_VOICES_SUBTRACTIVE = 6  # Subtractive: each voice = 3 oscillators internally

# Granular sample pool
_GRANULAR_SAMPLES = [
    "singing_bowl.ogg",
    "tibetan_bowl.ogg",
    "gong.ogg",
    "metal_hit.ogg",
]

# Per-mood subtractive character
_SUB_PROFILES = {
    "dark":       dict(waveforms=["saw","square"],     detune=(12,28), sub_mix=(0.35,0.65), filters=["lp","lp","bp"],  cutoff=(200,700),   res=(1.8,3.5), lfo_rate=(0.04,0.15), lfo_depth=(0.4,0.8),  lfo_shapes=["sine","triangle"]),
    "bright":     dict(waveforms=["triangle","saw"],   detune=(4,12),  sub_mix=(0.15,0.4),  filters=["bp","hp"],       cutoff=(1500,4000), res=(1.2,2.5), lfo_rate=(0.2,0.5),  lfo_depth=(0.2,0.5),  lfo_shapes=["sine","triangle"]),
    "cinematic":  dict(waveforms=["saw","triangle"],   detune=(8,22),  sub_mix=(0.4,0.9),   filters=["lp","lp","bp"],  cutoff=(400,1200),  res=(1.5,3.0), lfo_rate=(0.04,0.12),lfo_depth=(0.3,0.7),  lfo_shapes=["sine","triangle"]),
    "minimal":    dict(waveforms=["triangle","saw"],   detune=(3,8),   sub_mix=(0.3,0.6),   filters=["lp","off"],      cutoff=(600,1800),  res=(0.8,1.5), lfo_rate=(0.02,0.08),lfo_depth=(0.1,0.35), lfo_shapes=["sine"]),
    "industrial": dict(waveforms=["saw","square","square"], detune=(15,35), sub_mix=(0.5,1.0), filters=["lp","bp","hp"], cutoff=(300,2000), res=(2.0,4.5), lfo_rate=(0.1,0.4),  lfo_depth=(0.3,0.7),  lfo_shapes=["square","triangle","sine"]),
    "nature":     dict(waveforms=["triangle","saw"],   detune=(5,15),  sub_mix=(0.2,0.5),   filters=["lp","bp"],       cutoff=(500,2000),  res=(1.0,2.0), lfo_rate=(0.08,0.25),lfo_depth=(0.2,0.5),  lfo_shapes=["sine","triangle"]),
    "chaotic":    dict(waveforms=["saw","square","triangle"], detune=(10,40), sub_mix=(0.3,0.9), filters=["lp","bp","hp"], cutoff=(200,3000), res=(1.5,5.0), lfo_rate=(0.05,0.6), lfo_depth=(0.2,0.9),  lfo_shapes=["sine","triangle","square"]),
    "mixed":      dict(waveforms=["saw","triangle","square"], detune=(8,24),  sub_mix=(0.3,0.7), filters=["lp","bp"],    cutoff=(300,2000),  res=(1.2,3.0), lfo_rate=(0.05,0.3), lfo_depth=(0.2,0.6),  lfo_shapes=["sine","triangle"]),
}

_NAME_PARTS_A = [
    # elements & matter
    "Ancient", "Frozen", "Burning", "Hollow", "Crystal", "Iron", "Obsidian",
    "Amber", "Molten", "Ashen", "Copper", "Glacial", "Ember", "Cinnabar",
    "Basalt", "Quartz", "Titanium", "Onyx", "Alabaster", "Chromium",
    # space & cosmos
    "Solar", "Lunar", "Orbital", "Stellar", "Cosmic", "Nebular", "Astral",
    "Sidereal", "Zenith", "Galactic", "Ecliptic", "Crepuscular", "Solstice",
    "Equinox", "Perihelion", "Interstellar", "Sublunar", "Liminal",
    # physics & nature
    "Infinite", "Tectonic", "Spectral", "Magnetic", "Fractal", "Seismic",
    "Thermal", "Ionic", "Photonic", "Resonant", "Radiant", "Harmonic",
    "Kinetic", "Entropic", "Quantum", "Plasmid", "Ferrous", "Telluric",
    # atmosphere & water
    "Silent", "Phantom", "Void", "Abyssal", "Torrential", "Tempestuous",
    "Boreal", "Austral", "Riparian", "Pelagic", "Tidal",
    "Aeolian", "Nimbus", "Vernal", "Nocturnal", "Diurnal", "Ethereal",
    # sacred & mythic
    "Sacred", "Primordial", "Orphic", "Hermetic", "Arcane",
    "Druidic", "Shamanic", "Pythian", "Vedic", "Runic",
    "Sibylline", "Mantric", "Alchemical", "Telestial", "Chthonic",
]
_NAME_PARTS_B = [
    # acoustic & music
    "Resonance", "Choir", "Pulse", "Frequency", "Continuum", "Whisper",
    "Membrane", "Overtone", "Harmonic", "Timbre", "Tremolo", "Cadence",
    "Sustain", "Pedaltone", "Undertone", "Formant", "Partials", "Vibration",
    # architecture & space
    "Cathedral", "Chamber", "Expanse", "Abyss", "Horizon",
    "Nave", "Sanctum", "Threshold", "Corridor", "Atrium", "Canopy",
    "Alcove", "Cloister", "Vestibule", "Archway", "Labyrinth", "Terminus",
    # forces & phenomena
    "Drift", "Vortex", "Storm", "Field", "Pressure", "Machine", "Engine",
    "Current", "Torrent", "Cascade", "Gradient", "Flux", "Surge", "Tide",
    "Undertow", "Resonator", "Oscillation", "Convergence", "Emanation",
    # cosmic & mythic objects
    "Monolith", "Obelisk", "Nexus", "Meridian", "Apex", "Nadir",
    "Portal", "Sigil", "Glyph", "Oracle", "Mandala", "Yantra", "Stele",
    "Reliquary", "Totem", "Cipher", "Vessel", "Prism", "Talisman", "Codex",
]


def _random_name() -> str:
    return f"{random.choice(_NAME_PARTS_A)} {random.choice(_NAME_PARTS_B)}"


def _clamp(val, lo, hi):
    return max(lo, min(hi, val))


# ── Scale helpers ──────────────────────────────────────────────────────────────

_CHROMATIC_NOTES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

_SCALE_INTERVALS = {
    'major':            [0, 2, 4, 5, 7, 9, 11],
    'minor':            [0, 2, 3, 5, 7, 8, 10],
    'pentatonic_major': [0, 2, 4, 7, 9],
    'pentatonic_minor': [0, 3, 5, 7, 10],
    'dorian':           [0, 2, 3, 5, 7, 9, 10],
    'phrygian':         [0, 1, 3, 5, 7, 8, 10],
    'lydian':           [0, 2, 4, 6, 7, 9, 11],
    'mixolydian':       [0, 2, 4, 5, 7, 9, 10],
    'chromatic':        list(range(12)),
}


def _snap_to_scale(freq: float, key: str = 'C', scale: str = 'major') -> float:
    """Snap freq to the nearest note in the given key/scale."""
    key_idx = _CHROMATIC_NOTES.index(key) if key in _CHROMATIC_NOTES else 0
    intervals = _SCALE_INTERVALS.get(scale, _SCALE_INTERVALS['major'])
    scale_semitones = set((key_idx + i) % 12 for i in intervals)

    midi = 69.0 + 12.0 * math.log2(max(freq, 1.0) / 440.0)
    midi_round = round(midi)
    # Walk up/down from midi_round until we hit a scale note
    for delta in range(13):
        for sign in (0, 1, -1):
            candidate = midi_round + (delta * sign if sign else delta)
            if candidate % 12 in scale_semitones:
                return 440.0 * (2.0 ** ((candidate - 69) / 12.0))
    return freq  # fallback (should never reach here)


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

def generate_preset(mood: Optional[str] = None, seed: Optional[int] = None,
                    allowed_types: Optional[List[str]] = None,
                    harmonic_mode: bool = False,
                    harmonic_key: str = 'C',
                    harmonic_scale: str = 'major',
                    intent: Optional[dict] = None) -> dict:
    """
    Generate a fully random preset, optionally biased by mood.
    allowed_types: list of layer types to allow, e.g. ["fm", "subtractive", "granular"].
                   Defaults to ["fm", "subtractive", "granular"].
    Returns a raw dict ready to be saved as YAML.
    """
    if seed is not None:
        random.seed(seed)

    if not allowed_types:
        allowed_types = ["fm", "subtractive", "granular"]

    # Select mood profile or use neutral defaults
    if mood and mood in _MOOD_PROFILES:
        profile = _MOOD_PROFILES[mood]
    else:
        profile = random.choice(list(_MOOD_PROFILES.values()))
        mood = "mixed"

    sub_profile = _SUB_PROFILES.get(mood, _SUB_PROFILES["mixed"])
    intent_values = dict(_MOOD_INTENTS.get(mood, _MOOD_INTENTS["mixed"]))
    for key, value in (intent or {}).items():
        if key in intent_values:
            try:
                intent_values[key] = _clamp(float(value), 0.0, 1.0)
            except (TypeError, ValueError):
                pass
    density    = intent_values["density"]
    motion     = intent_values["motion"]
    space      = intent_values["space"]
    tonality   = intent_values["tonality"]
    weight     = intent_values["weight"]
    stability  = intent_values["stability"]
    brightness = intent_values["brightness"]
    evolution  = intent_values["evolution"]

    # Intent controls are authoritative. Moods seed these values, but once a
    # user moves a macro it must be able to cross the original mood's range.
    brightness_curve = brightness ** 2
    def spectral_cutoff(base: float) -> float:
        return _clamp(base * (.35 + brightness * 1.1) + brightness_curve * 6500, 40, 12000)

    name = _random_name()
    slug = name.lower().replace(" ", "_")

    # Duration
    duration_pool = [60, 90] if evolution < .33 else [90, 120, 150] if evolution < .67 else [120, 150, 180]
    duration = random.choice(duration_pool)

    # Number of layers — capped at _MAX_LAYERS for streaming safety
    layer_weights = [70, 25, 5] if density < .33 else [20, 55, 25] if density < .67 else [5, 30, 65]
    n_layers = random.choices([1, 2, 3], weights=layer_weights)[0]

    layers = []
    for i in range(n_layers):
        root_shift_octaves = (brightness - .5) * 3.2 - (weight - .5) * 1.0
        root_factor = 2 ** root_shift_octaves
        root_range = tuple(_clamp(value * root_factor, 20, 6000) for value in profile["root_range"])
        root = random.uniform(*root_range)
        if harmonic_mode:
            root = _snap_to_scale(root, harmonic_key, harmonic_scale)
        else:
            root = 440 * (2 ** (round(12 * math.log2(root / 440)) / 12))

        layer_type = random.choice(allowed_types)

        if tonality > .7:
            ratios = random.choice([[1.0, 2.0], [1.0, 2.0, 3.0], [1.0, 1.5, 2.0]])
        elif tonality < .3:
            ratios = random.choice([[1.0, 1.37, 2.11], [0.5, 1.0, 1.71, 2.63], [1.0, 1.41, 2.27]])
        else:
            ratios = random.choice(profile["ratios_pool"])
        drift  = random.uniform(*profile["drift_range"]) * (.25 + (1 - stability) * 1.5)

        moving_trajectories = _TRAJECTORIES_X[:-1]
        trajectory_x = random.choice(moving_trajectories) if random.random() < motion else "none"
        spatial = {
            "quadrant":     random.choice(_QUADRANTS),
            "speed":        round(random.uniform(0.001, 0.004 + motion * 0.026), 4),
            "trajectory_x": trajectory_x,
            "trajectory_y": random.choice(_TRAJECTORIES_Y) if motion > .35 else "none",
        }
        dynamics = {
            "mix":     round(random.uniform(0.4, 1.2), 2),
            "amp_min": round(random.uniform(0.002, 0.02), 4),
            "amp_max": round(random.uniform(0.03, 0.08), 4),
            "drift":   round(drift, 4),
        }

        if layer_type == "subtractive":
            voices = min(max(1, round(random.randint(*profile["voice_range"]) * (.55 + density * .9))), _MAX_VOICES_SUBTRACTIVE)
            layer = {
                "name":    _layer_name_for_freq(root, i),
                "enabled": True,
                "type":    "subtractive",
                "synthesis":     {"root": round(root, 2), "voices": voices, "ratios": ratios},
                "fm":            {"ratios": [1.0], "index": 0.0},
                "dynamics":      dynamics,
                "spatial_motion": spatial,
                "waveform":        random.choice(sub_profile["waveforms"]),
                "detune_cents":    round(random.uniform(*sub_profile["detune"]) * (.35 + (1 - stability) * 1.1), 1),
                "sub_mix":         round(random.uniform(*sub_profile["sub_mix"]), 2),
                "filter_type":     random.choice(sub_profile["filters"]),
                "filter_cutoff":   round(spectral_cutoff(random.uniform(*sub_profile["cutoff"])), 1),
                "filter_resonance":round(random.uniform(*sub_profile["res"]), 2),
                "filter_lfo_rate": round(random.uniform(*sub_profile["lfo_rate"]) * (.3 + motion * 1.2), 3),
                "filter_lfo_depth":round(random.uniform(*sub_profile["lfo_depth"]) * (.35 + evolution), 2),
                "filter_lfo_shape":random.choice(sub_profile["lfo_shapes"]),
                "chorus_rate":  round(random.uniform(0.2, 0.8), 2),
                "chorus_depth": round(random.uniform(0.004, 0.015), 4),
                "chorus_mix":   round(random.uniform(0.1, 0.5), 2),
                "chorus_voices": random.choice([2, 3]),
                "noise_amount": round(random.uniform(0, (1 - tonality) * .14), 3),
            }

        elif layer_type == "granular":
            voices = min(max(1, round(random.randint(*profile["voice_range"]) * (.55 + density * .9))), _MAX_VOICES_FM)
            layer = {
                "name":    _layer_name_for_freq(root, i),
                "enabled": True,
                "type":    "granular",
                "source":      random.choice(_GRANULAR_SAMPLES),
                "grain_size":  round(random.uniform(40, 200), 1),
                "density":     round(random.uniform(6, 14 + density * 28), 1),
                "pitch_spread":round(random.uniform(0.05, 0.15 + (1 - stability) * 0.75), 2),
                "position":    round(random.uniform(0.1, 0.9), 2),
                "scatter":     round(random.uniform(0.1, 0.25 + evolution * 0.7), 2),
                "envelope":    random.choice(["hann", "triangle", "trapezoid"]),
                "synthesis":     {"root": round(root, 2), "voices": voices, "ratios": ratios},
                "fm":            {"ratios": [1.0], "index": 0.0},
                "dynamics":      dynamics,
                "spatial_motion": spatial,
                "filter_type":     random.choice(["off", "lp", "bp"]),
                "filter_cutoff":   round(spectral_cutoff(random.uniform(500.0, 3000.0)), 1),
                "filter_resonance":round(random.uniform(0.7, 2.0), 2),
                "filter_lfo_rate": round(random.uniform(0.05, 0.3), 3),
                "filter_lfo_depth":round(random.uniform(0.0, 0.4), 2),
                "filter_lfo_shape":random.choice(["sine", "triangle"]),
                "chorus_rate":  round(random.uniform(0.3, 0.7), 2),
                "chorus_depth": round(random.uniform(0.003, 0.01), 4),
                "chorus_mix":   round(random.uniform(0.0, 0.08 + space * 0.35), 2),
                "chorus_voices": 2,
            }

        else:  # fm
            voices = min(max(1, round(random.randint(*profile["voice_range"]) * (.55 + density * .9))), _MAX_VOICES_FM)
            fm_ratios = random.choice(
                [[1.0], [1.0, 1.5], [1.0, 2.0], [1.0, 2.5, 3.0]] if tonality >= .5
                else [[1.0, 1.37], [1.0, 1.71], [1.0, 2.27, 3.13]]
            )
            fm_index  = random.uniform(*profile["fm_index_range"]) * (1.35 - tonality * .85)
            layer = {
                "name":    _layer_name_for_freq(root, i),
                "enabled": True,
                "type":    "fm",
                "synthesis":     {"root": round(root, 2), "voices": voices, "ratios": ratios},
                "fm":            {"ratios": fm_ratios, "index": round(fm_index, 3)},
                "dynamics":      dynamics,
                "spatial_motion": spatial,
                "filter_type":     random.choice(["off", "off", "lp", "hp"]),
                "filter_cutoff":   round(spectral_cutoff(random.uniform(400.0, 4000.0)), 1),
                "filter_resonance":round(random.uniform(0.7, 2.0), 2),
                "filter_lfo_rate": round(random.uniform(0.05, 0.2), 3),
                "filter_lfo_depth":round(random.uniform(0.0, 0.3), 2),
                "filter_lfo_shape":random.choice(["sine", "triangle"]),
                "chorus_rate":  round(random.uniform(0.3, 0.8), 2),
                "chorus_depth": round(random.uniform(0.003, 0.01), 4),
                "chorus_mix":   round(random.uniform(0.0, 0.08 + space * 0.38), 2),
                "chorus_voices": random.choice([2, 3]),
                "noise_amount": round(random.uniform(0, (1 - tonality) * .1), 3),
            }

        layers.append(layer)

    # Reverb
    reverb = {
        "enabled": True,
        "room_size": round(_clamp(random.uniform(*profile["reverb_room"]) * (.55 + space * .65), .1, 1), 2),
        "decay": round(_clamp(random.uniform(*profile["reverb_decay"]) + (space - .5) * .12, .55, .99), 2),
        "damping": round(_clamp(random.uniform(*profile["reverb_damping"]) + (.5 - brightness) * .75, .05, .9), 2),
        "modulation": round(random.uniform(0.03, 0.12 + evolution * .5), 2),
        "wet": round(random.uniform(.06 + space * .18, .14 + space * .48), 2),
        "predelay": round(random.uniform(0.005, 0.015 + space * .065), 3),
    }

    # Earth
    earth = None
    if random.random() < _clamp(profile["earth_prob"] + (weight - .5) * .65, 0, 1):
        earth = {
            "enabled": True,
            "tectonic_frequency": random.randint(12, 24),
            "pressure": round(random.uniform(0.15, 0.5), 2),
            "movement": round(random.uniform(0.005, 0.03), 3),
        }

    # Air
    air = None
    air_probability = 1.0 if brightness >= .8 else _clamp(profile["air_prob"] + (brightness - .5) * .75, 0, 1)
    if random.random() < air_probability:
        air = {
            "enabled": True,
            "intensity": round(random.uniform(0.05 + brightness * .12, 0.16 + brightness * .3), 2),
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
            "intent": {key: round(value, 3) for key, value in intent_values.items()},
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
