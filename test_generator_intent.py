import unittest
from pathlib import Path

from engine.generator import generate_preset


class GeneratorIntentTests(unittest.TestCase):
    def test_classic_generates_essential_style_drones(self):
        for seed in range(20):
            preset = generate_preset("classic", seed=seed)
            self.assertEqual(preset["meta"]["mood"], ["classic", "essential", "warm"])
            self.assertTrue(all(layer["type"] == "fm" for layer in preset["layers"]))
            self.assertTrue(all(50 <= layer["synthesis"]["root"] <= 230
                                for layer in preset["layers"]))
            self.assertTrue(all(layer["fm"]["index"] <= 0.18
                                for layer in preset["layers"]))
            self.assertEqual(preset["spatial"]["wetness"], 0.5)
            self.assertGreaterEqual(preset["saturation"], 0.2)
            self.assertLessEqual(preset["saturation"], 0.4)
            self.assertNotIn("earth", preset)
            self.assertNotIn("air", preset)

    def test_named_moods_ignore_expressive_intent(self):
        intent = {"brightness": 1, "motion": 1, "density": 1, "weight": 0}
        for mood in ("dark", "bright", "cinematic", "minimal", "industrial", "nature"):
            self.assertEqual(generate_preset(mood, seed=7),
                             generate_preset(mood, seed=7, intent=intent))

    def test_custom_uses_expressive_intent(self):
        dark = generate_preset("custom", seed=7, intent={"brightness": 0})
        bright = generate_preset("custom", seed=7, intent={"brightness": 1})
        self.assertNotEqual(dark, bright)
        self.assertEqual(bright["meta"]["intent"]["brightness"], 1.0)

    def test_generated_motion_stays_in_drone_rate_ranges(self):
        moods = ("dark", "bright", "cinematic", "classic", "minimal", "industrial", "nature")
        for mood in moods:
            for layer_type in ("fm", "subtractive", "granular", "wavetable"):
                for seed in range(10):
                    preset = generate_preset(mood, seed=seed, allowed_types=[layer_type])
                    for layer in preset["layers"]:
                        self.assertLessEqual(layer["filter_lfo_rate"], 0.12)
                        self.assertLessEqual(layer["spatial_motion"]["speed"], 0.005)

    def test_wavetable_generation_is_bundled_slow_and_drone_oriented(self):
        expected_sources = {
            "wavetables/ct-wt-1784147249-warpy_cherries-256-2048-32.wav",
            "wavetables/ct-wt-1783861884-rnd___modified-256-2048-32_8a119dca.wav",
            "wavetables/ct-wt-1784146344-ct_v1_6_0___new_cherry_picker-256-2048-32.wav",
            "wavetables/ct-wt-1784146377-chopper-256-2048-32.wav",
        }
        for seed in range(30):
            preset = generate_preset("minimal", seed=seed, allowed_types=["wavetable"])
            for layer in preset["layers"]:
                self.assertEqual(layer["type"], "wavetable")
                self.assertIn(layer["wavetable_source"], expected_sources)
                self.assertTrue(Path("samples", layer["wavetable_source"]).is_file())
                self.assertIn(layer["wavetable_scan_mode"],
                              {"smooth_random", "sine", "pingpong", "forward", "reverse"})
                self.assertGreaterEqual(layer["wavetable_scan_rate"], 0.001)
                self.assertLessEqual(layer["wavetable_scan_rate"], 0.03)
                self.assertFalse(layer["wavetable_audio_rate_scan"])
                self.assertGreaterEqual(layer["wavetable_scan_start"], 0.0)
                self.assertLessEqual(layer["wavetable_scan_end"], 1.0)
                self.assertGreaterEqual(layer["wavetable_scan_end"] - layer["wavetable_scan_start"], 0.179)
                self.assertIn(layer["wavetable_tremor_amount"], {0, 2, 3, 4, 5, 6, 7, 8, 9, 10})
                self.assertGreaterEqual(layer["wavetable_tremor_rate"], 0.05)
                self.assertLessEqual(layer["wavetable_tremor_rate"], 0.3)
                self.assertLessEqual(layer["synthesis"]["root"], 330.0)

    def test_opted_in_wavetable_is_always_present(self):
        for seed in range(100):
            preset = generate_preset(
                "minimal", seed=seed,
                allowed_types=["fm", "subtractive", "wavetable"],
            )
            layer_types = {layer["type"] for layer in preset["layers"]}
            self.assertIn("wavetable", layer_types)
            self.assertGreaterEqual(len(preset["layers"]), 2)

    def test_all_opted_in_special_engines_are_present(self):
        for seed in range(30):
            preset = generate_preset(
                "cinematic", seed=seed,
                allowed_types=["fm", "subtractive", "granular", "wavetable"],
            )
            layer_types = {layer["type"] for layer in preset["layers"]}
            self.assertIn("granular", layer_types)
            self.assertIn("wavetable", layer_types)

    def test_shipped_generator_uses_legacy_controls(self):
        static_html = Path("engine/static/index.html").read_text(encoding="utf-8")
        docs_html = Path("docs/index.html").read_text(encoding="utf-8")
        self.assertEqual(static_html, docs_html)
        self.assertNotIn('data-mood="custom"', static_html)
        self.assertIn('data-mood="classic"', static_html)
        self.assertIn("if (selectedMood === 'classic')", static_html)
        self.assertNotIn('id="generator-mood-settings"', static_html)
        self.assertIn('id="gen-type-fm" checked', static_html)
        self.assertIn('id="gen-type-subtractive" checked', static_html)
        self.assertIn('id="gen-type-granular"', static_html)
        self.assertIn('id="gen-type-wavetable"', static_html)
        self.assertNotIn('id="gen-type-wavetable" checked', static_html)
        self.assertIn("allowedTypes.push('wavetable')", static_html)
        self.assertIn("let selectedMood = null", static_html)


if __name__ == "__main__":
    unittest.main()
