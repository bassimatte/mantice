import unittest
from pathlib import Path

from engine.generator import generate_preset


class GeneratorIntentTests(unittest.TestCase):
    def test_minimal_uses_essential_style_tonality(self):
        preset = generate_preset("minimal", seed=7)
        self.assertEqual(preset["meta"]["intent"]["tonality"], 0.68)

    def test_shipped_minimal_controls_match_backend(self):
        static_html = Path("engine/static/index.html").read_text(encoding="utf-8")
        docs_html = Path("docs/index.html").read_text(encoding="utf-8")
        self.assertEqual(static_html, docs_html)
        self.assertIn("tonality:68", static_html)
        self.assertIn('id="intent-tonality" min="0" max="100" value="68"', static_html)


if __name__ == "__main__":
    unittest.main()
