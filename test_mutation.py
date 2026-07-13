import copy
import math
import unittest

from engine.generator import mutate_ui_params
from engine.web_server import _preset_to_ui_params


def mutation_fixture():
    common = {
        "voices": 3, "volume_db": -6.0, "drift": 0.004, "pan": 0.0, "width": 1.0,
        "filter_type": "lp", "filter_cutoff": 1200.0, "filter_resonance": 1.5,
        "filter_lfo_rate": 0.03, "filter_lfo_depth": 0.25, "speed": 0.008,
        "quadrant": "center", "trajectory_x": "drift", "chorus_rate": 0.2,
        "chorus_depth": 0.005, "chorus_mix": 0.1, "flanger_wet": 0.0,
        "phaser_wet": 0.0, "distortion_drive": 0.0,
    }
    return {
        "name": "Mutation Test", "duration": 90, "spatial_depth": 1.2,
        "spatial_wet": 0.5, "saturation": 0.3,
        "reverb": {"mix": 0.4, "decay_trim": 1.0, "pre_delay_ms": 20.0,
                   "modulation_depth": 0.2, "space": "hall"},
        "earth": {"tectonic_frequency": 18, "pressure": 0.4, "movement": 0.02},
        "air": {"intensity": 0.1, "movement": 0.01, "turbulence": 0.04},
        "shimmer": {"wet": 0.1, "feedback": 0.4},
        "master": {"eq_bass_db": 0.0, "eq_lo_mid_db": 0.0,
                   "eq_hi_mid_db": 0.0, "eq_air_db": 0.0},
        "layers": [
            {**common, "name": "FM", "type": "fm", "root": 55.0, "fm_index": 0.5,
             "harmonic_decay": 0.7, "noise_amount": 0.0, "spread": 1.0, "blend": 1.0},
            {**common, "name": "Sub", "type": "subtractive", "root": 110.0,
             "detune_cents": 8.0, "sub_mix": 0.3, "waveform": "saw"},
            {**common, "name": "Grains", "type": "granular", "root": 220.0,
             "source": "singing_bowl.ogg", "grain_size": 80.0, "density": 15.0,
             "pitch_spread": 0.3, "position": 0.5, "scatter": 0.4,
             "pitch_semitones": 0.0, "position_chaos": 0.3},
            {**common, "name": "Table", "type": "wavetable", "root": 440.0,
             "wavetable_source": "wavetables/test.wav", "wavetable_position": 0.2,
             "wavetable_scan_start": 0.0, "wavetable_scan_end": 1.0,
             "wavetable_scan_rate": 0.01, "wavetable_scan_mode": "pingpong",
             "wavetable_detune_cents": 7.0},
        ],
    }


class BalancedMutationTests(unittest.TestCase):
    def test_loaded_preset_keeps_mutatable_stereo_motion_and_effects(self):
        layer = {
            "name": "Existing", "type": "fm", "root": 110.0,
            "pan": -0.4, "width": 1.6, "spread": 0.7, "blend": 0.8,
            "quadrant": "rear_left", "trajectory_x": "orbit", "speed": 0.006,
            "flanger_wet": 0.2, "phaser_wet": 0.3,
        }
        ui_layer = _preset_to_ui_params({"meta": {"name": "Loaded"}, "layers": [layer]})["layers"][0]
        for key in ("pan", "width", "spread", "blend", "flanger_wet", "phaser_wet"):
            self.assertEqual(ui_layer[key], layer[key])
        self.assertEqual(ui_layer["spatial_motion"]["quadrant"], "rear_left")
        self.assertEqual(ui_layer["spatial_motion"]["trajectory_x"], "orbit")
        self.assertEqual(ui_layer["spatial_motion"]["speed"], 0.006)

    def test_zero_amount_is_identical_and_input_is_never_modified(self):
        original = mutation_fixture()
        snapshot = copy.deepcopy(original)
        self.assertEqual(mutate_ui_params(original, 0.0, seed=1), snapshot)
        mutate_ui_params(original, 1.0, seed=2)
        self.assertEqual(original, snapshot)

    def test_pitch_moves_are_occasional_and_preserve_intervals(self):
        original = mutation_fixture()
        moved = 0
        for seed in range(200):
            result = mutate_ui_params(original, 0.3, seed=seed)
            roots = [layer["root"] for layer in result["layers"]]
            if roots[0] != original["layers"][0]["root"]:
                moved += 1
                for index in range(1, len(roots)):
                    original_ratio = original["layers"][index]["root"] / original["layers"][0]["root"]
                    mutated_ratio = roots[index] / roots[0]
                    self.assertTrue(math.isclose(mutated_ratio, original_ratio, rel_tol=2e-4))
        self.assertGreater(moved, 30)
        self.assertLess(moved, 90)

    def test_default_mutation_covers_timbre_space_and_each_engine(self):
        original = mutation_fixture()
        changed = set()
        for seed in range(80):
            result = mutate_ui_params(original, 0.3, seed=seed)
            if result["reverb"]["mix"] != original["reverb"]["mix"]: changed.add("reverb")
            for before, after in zip(original["layers"], result["layers"]):
                for key in before:
                    if after.get(key) != before.get(key):
                        changed.add(f"{before['type']}.{key}")
                self.assertEqual(after["type"], before["type"])
                if "source" in before: self.assertEqual(after["source"], before["source"])
                if "wavetable_source" in before: self.assertEqual(after["wavetable_source"], before["wavetable_source"])
                self.assertLessEqual(after["speed"], 0.05)
        expected = {
            "reverb", "fm.volume_db", "fm.filter_cutoff", "fm.fm_index", "fm.pan",
            "subtractive.detune_cents", "subtractive.sub_mix", "granular.grain_size",
            "granular.position", "wavetable.wavetable_position",
            "wavetable.wavetable_scan_rate", "wavetable.wavetable_detune_cents",
        }
        self.assertTrue(expected.issubset(changed), expected - changed)


if __name__ == "__main__":
    unittest.main()
