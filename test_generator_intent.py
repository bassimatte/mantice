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

    def test_minimal_uses_essential_style_tonality(self):
        preset = generate_preset("minimal", seed=7)
        self.assertEqual(preset["meta"]["intent"]["tonality"], 0.68)

    def test_shipped_minimal_controls_match_backend(self):
        static_html = Path("engine/static/index.html").read_text(encoding="utf-8")
        docs_html = Path("docs/index.html").read_text(encoding="utf-8")
        self.assertEqual(static_html, docs_html)
        self.assertIn("tonality:68", static_html)
        self.assertIn('data-mood="classic"', static_html)
        self.assertIn("classic:    { density:28", static_html)
        self.assertIn('id="intent-tonality" min="0" max="100" value="68"', static_html)


if __name__ == "__main__":
    unittest.main()
