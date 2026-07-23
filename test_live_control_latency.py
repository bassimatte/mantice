"""Regression checks for responsive browser live controls."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
STATIC_UI = ROOT / "engine" / "static" / "index.html"
PUBLISHED_UI = ROOT / "docs" / "index.html"
WEB_SERVER = ROOT / "engine" / "web_server.py"


class LiveControlLatencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = STATIC_UI.read_text(encoding="utf-8")
        cls.published_html = PUBLISHED_UI.read_text(encoding="utf-8")
        cls.server = WEB_SERVER.read_text(encoding="utf-8")

    def test_frontend_copies_match(self):
        self.assertEqual(self.html, self.published_html)

    def test_mute_and_solo_use_fast_crossfade(self):
        self.assertIn("const FAST_LAYER_XFADE_SECS = 0.05;", self.html)
        self.assertGreaterEqual(
            self.html.count("liveReload(FAST_LAYER_XFADE_SECS);"), 2
        )

    def test_immediate_reload_cancels_pending_debounce(self):
        reload_start = self.html.index("function liveReload(crossfadeOverride = null)")
        reload_body = self.html[reload_start:reload_start + 900]
        self.assertIn("clearTimeout(_liveReloadTimer)", reload_body)
        self.assertIn("_liveReloadTimer = null", reload_body)

    def test_preview_uses_low_latency_chunks_and_lookahead(self):
        self.assertIn("const CHUNK_SIZE = 1024;", self.html)
        self.assertIn("chunk_size = 1024  # ~46ms", self.server)
        self.assertIn("max_ahead = 2  # ~93ms", self.server)


if __name__ == "__main__":
    unittest.main()
