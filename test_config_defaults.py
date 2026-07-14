import unittest

from engine import config


class RenderConfigDefaultsTests(unittest.TestCase):
    def test_standard_python_render_matches_web_export_resolution(self):
        self.assertEqual(config.SAMPLE_RATE, 22_050)
        self.assertEqual(config.BIT_DEPTH, "PCM_16")

    def test_hires_resolution_remains_unchanged(self):
        self.assertEqual(config.HIRES_SAMPLE_RATE, 48_000)
        self.assertEqual(config.HIRES_BIT_DEPTH, "PCM_24")


if __name__ == "__main__":
    unittest.main()
