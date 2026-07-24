import unittest

import yaml

from engine.preset_loader import load_preset_from_yaml_string
from engine.preset_schema import CURRENT_PRESET_SCHEMA_VERSION
from engine.web_server import _ui_params_to_preset


class WebsitePresetExportTests(unittest.TestCase):
    def test_unversioned_legacy_preset_migrates_to_current_schema(self):
        loaded = load_preset_from_yaml_string(yaml.safe_dump({
            "name": "Legacy named preset",
            "master": {"eq": {"mid_db": -2.5, "mid_hz": 310, "mid_q": 0.8}},
            "layers": [{"type": "fm", "root": 110.0}],
        }))

        self.assertEqual(loaded["schema_version"], CURRENT_PRESET_SCHEMA_VERSION)
        self.assertEqual(loaded["meta"]["name"], "Legacy named preset")
        self.assertEqual(loaded["master"]["eq"]["lo_mid_db"], -2.5)
        self.assertEqual(loaded["master"]["eq"]["lo_mid_hz"], 310)
        self.assertEqual(loaded["master"]["eq"]["lo_mid_q"], 0.8)
        self.assertNotIn("mid_db", loaded["master"]["eq"])

    def test_unknown_future_schema_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, "newer than this Mantice build"):
            load_preset_from_yaml_string(yaml.safe_dump({
                "schema_version": CURRENT_PRESET_SCHEMA_VERSION + 1,
                "layers": [{"type": "fm", "root": 110.0}],
            }))

    def test_new_website_export_declares_current_schema(self):
        exported = _ui_params_to_preset({
            "name": "Versioned",
            "layers": [{"type": "fm", "root": 110.0}],
        })
        self.assertEqual(
            exported["schema_version"],
            CURRENT_PRESET_SCHEMA_VERSION,
        )

    def test_missing_master_uses_website_defaults(self):
        loaded = load_preset_from_yaml_string(yaml.safe_dump({
            "name": "Legacy preset",
            "layers": [{"type": "fm", "root": 110.0}],
        }))

        self.assertEqual(loaded["master"]["comp"], {
            "threshold_db": -18.0,
            "ratio": 2.5,
            "attack_ms": 50.0,
            "release_ms": 200.0,
            "knee_db": 3.0,
            "makeup_db": 4.0,
        })
        self.assertEqual(loaded["master"]["output_gain_db"], 0.0)

    def test_partial_master_overrides_only_explicit_values(self):
        loaded = load_preset_from_yaml_string(yaml.safe_dump({
            "name": "Custom master",
            "master": {
                "comp": {"ratio": 4.0, "makeup_db": 1.0},
                "output_gain_db": -2.0,
            },
            "layers": [{"type": "fm", "root": 110.0}],
        }))

        self.assertEqual(loaded["master"]["comp"]["ratio"], 4.0)
        self.assertEqual(loaded["master"]["comp"]["makeup_db"], 1.0)
        self.assertEqual(loaded["master"]["comp"]["threshold_db"], -18.0)
        self.assertEqual(loaded["master"]["output_gain_db"], -2.0)

    def test_flat_website_export_reloads_all_engine_parameters(self):
        common = {
            "voices": 3, "root": 110.0, "ratios": [1.0, 1.5],
            "fm_ratios": [1.0, 2.0], "fm_index": 0.37,
            "volume_db": -7.5, "amp_min": 0.01, "amp_max": 0.04,
            "drift": 0.006, "quadrant": "rear_left", "speed": 0.009,
            "trajectory_x": "drift", "trajectory_y": "none",
            "pan": -0.3, "width": 1.4, "spread": 0.8, "blend": 0.65,
            "harmonics": 5, "harmonic_decay": 0.62,
            "noise_amount": 0.07, "noise_color": "brown",
            "elevation": 25.0, "elevation_motion": "float",
            "elevation_speed": 0.08, "elevation_range": 45.0,
            "chorus_rate": 0.17, "chorus_depth": 0.008,
            "chorus_mix": 0.22, "chorus_voices": 3,
            "filter_type": "lp", "filter_cutoff": 930.0,
            "filter_resonance": 2.1, "filter_lfo_rate": 0.035,
            "filter_lfo_depth": 0.42, "filter_lfo_shape": "triangle",
            "filter_vowel": "u", "distortion_drive": 0.4,
            "distortion_type": "hard", "flanger_wet": 0.13,
            "flanger_rate": 0.11, "flanger_depth": 0.52,
            "flanger_feedback": 0.31, "phaser_wet": 0.19,
            "phaser_rate": 0.14, "phaser_depth": 0.63,
            "phaser_center_hz": 740.0, "phaser_feedback": -0.18,
            "phaser_stages": 6, "tuning_degree": "perfect_fifth",
            "automation": {"volume_db": {"enabled": True, "breakpoints": []}},
        }
        params = {
            "name": "Roundtrip",
            "duration": 73,
            "spatial_depth": 1.7,
            "spatial_wet": 0.64,
            "saturation": 0.61,
            "tuning_mode": "ji",
            "tonic_hz": 432.0,
            "tuning_system_ji": "7limit_ji",
            "pure_mode": True,
            "master": {"output_gain_db": 1.5},
            "automation": {"saturation": {"enabled": True, "breakpoints": []}},
            "layers": [
                {**common, "name": "FM", "type": "fm"},
                {**common, "name": "Sub", "type": "subtractive",
                 "waveform": "square", "detune_cents": 17.0, "sub_mix": 0.46},
                {**common, "name": "Grains", "type": "granular",
                 "source": "gong.ogg", "grain_size": 123.0, "density": 18.0,
                 "pitch_spread": 0.56, "position": 0.37, "scatter": 0.72,
                 "envelope": "triangle", "position_mode": "random",
                 "position_chaos": 0.41, "pitch_mode": "stretch",
                 "pitch_semitones": -5.0, "sample_root_hz": 196.0,
                 "stereo_width": 0.67},
                {**common, "name": "Table", "type": "wavetable",
                 "wavetable_source": "wavetables/test.wav",
                 "wavetable_frame_size": 2048, "wavetable_position": 0.28,
                 "wavetable_scan_start": 0.12, "wavetable_scan_end": 0.83,
                 "wavetable_scan_rate": 0.007, "wavetable_scan_mode": "forward",
                 "wavetable_scan_shape": "triangle", "wavetable_scan_direction": "reverse",
                 "wavetable_detune_cents": 11.0, "wavetable_name": "Test Table",
                 "wavetable_unison_mode": "hard", "wavetable_unison_spread": 0.93,
                 "wavetable_unison_blend": 0.61,
                 "wavetable_sha256": "a" * 64,
                 "wavetable_source_url": "https://example.test/table",
                 "wavetable_creator": "Tester", "wavetable_license": "CC0"},
            ],
        }

        exported = _ui_params_to_preset(params)
        loaded = load_preset_from_yaml_string(yaml.safe_dump(exported))

        self.assertEqual([layer["type"] for layer in loaded["layers"]],
                         ["fm", "subtractive", "granular", "wavetable"])
        for key in ("duration", "spatial_depth", "spatial_wet", "saturation",
                    "tuning_mode", "tonic_hz", "tuning_system_ji", "pure_mode",
                    "master", "automation"):
            self.assertEqual(loaded[key], exported[key], key)

        keys_by_type = {
            "fm": ("fm_index", "harmonics", "noise_amount", "spread", "blend"),
            "subtractive": ("waveform", "detune_cents", "sub_mix"),
            "granular": ("source", "grain_size", "density", "pitch_spread",
                         "position", "scatter", "envelope", "position_mode",
                         "position_chaos", "pitch_mode", "pitch_semitones",
                         "sample_root_hz", "stereo_width"),
            "wavetable": ("wavetable_source", "wavetable_frame_size",
                          "wavetable_position", "wavetable_scan_start",
                          "wavetable_scan_end", "wavetable_scan_rate",
                          "wavetable_scan_mode", "wavetable_detune_cents",
                          "wavetable_scan_shape", "wavetable_scan_direction",
                          "wavetable_unison_mode", "wavetable_unison_spread",
                          "wavetable_unison_blend",
                          "wavetable_name", "wavetable_sha256",
                          "wavetable_source_url", "wavetable_creator",
                          "wavetable_license"),
        }
        shared_keys = ("root", "tuning_degree", "voices", "ratios", "volume_db",
                       "drift", "pan", "width", "filter_type", "filter_cutoff",
                       "chorus_mix", "distortion_drive", "flanger_wet",
                       "phaser_wet", "automation")
        for before, after in zip(exported["layers"], loaded["layers"]):
            for key in shared_keys + keys_by_type[before["type"]]:
                self.assertEqual(after[key], before[key], f"{before['type']}.{key}")


if __name__ == "__main__":
    unittest.main()
