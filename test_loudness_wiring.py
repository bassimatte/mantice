import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class LoudnessWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "engine" / "static" / "index.html").read_text()
        cls.server = (ROOT / "engine" / "web_server.py").read_text()
        cls.cli = (ROOT / "main.py").read_text()

    def test_website_balanced_loudness_is_enabled_by_default(self):
        self.assertIn('id="normalize-loudness-toggle" data-state="1"', self.html)
        self.assertIn("normalize_loudness: $('normalize-loudness-toggle').dataset.state === '1'", self.html)
        self.assertIn("Original dynamics", self.html)

    def test_web_render_uses_bounded_loudness_normalization(self):
        self.assertIn('body.get("normalize_loudness", True)', self.server)
        self.assertIn("raw = loudness_normalize(raw, render_sr)", self.server)
        self.assertIn("preview_loudness=False", self.server)

    def test_mobile_preview_uses_live_loudness_control(self):
        self.assertIn("render_mode=True, preview_loudness=True", self.server)

    def test_cli_can_retain_original_dynamics(self):
        self.assertIn('"--original-dynamics"', self.cli)
        self.assertIn("audio = loudness_normalize(audio, sr)", self.cli)


if __name__ == "__main__":
    unittest.main()
