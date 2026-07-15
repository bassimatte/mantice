import unittest
from pathlib import Path


class FirstGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.static_html = Path("engine/static/index.html").read_text(encoding="utf-8")
        cls.docs_html = Path("docs/index.html").read_text(encoding="utf-8")

    def test_deployed_and_local_guides_are_identical(self):
        self.assertEqual(self.static_html, self.docs_html)

    def test_guide_is_persistent_reopenable_and_shared_link_safe(self):
        self.assertIn("mantice_first_breath_complete_v1", self.static_html)
        self.assertIn('id="btn-first-guide"', self.static_html)
        self.assertIn("window.location.hash.includes('shared=')", self.static_html)
        self.assertIn("if (!firstGuideWasCompleted() && !isSharedLink)", self.static_html)

    def test_deep_dive_is_optional_and_covers_advanced_workflow(self):
        self.assertIn('id="btn-deep-guide"', self.static_html)
        self.assertIn("const DEEP_DIVE_STEPS = [", self.static_html)
        self.assertIn("function openDeepDiveGuide()", self.static_html)
        for selector in ("#layers-card > h2", "#tuning-panel", "#global-fx-card > h2",
                         "#master-card > h2", "#automation-card > h2",
                         "#journey-card > h2", "#btn-files"):
            self.assertIn(selector, self.static_html)
        self.assertIn("Choose a synthesis engine", self.static_html)
        self.assertIn("FM for pure-to-metallic spectra", self.static_html)
        self.assertIn("Shape each layer", self.static_html)
        self.assertIn("distortion, chorus, flanger and phaser", self.static_html)
        self.assertIn("openDeepDiveLayerTab('synth')", self.static_html)
        self.assertIn("openDeepDiveLayerTab('fx')", self.static_html)
        self.assertIn("activeGuideIsFirst &&", self.static_html)

    def test_guide_uses_real_sound_controls(self):
        self.assertIn("const FIRST_GUIDE_STEPS = [", self.static_html)
        self.assertIn("loadFirstGuideClassicStart", self.static_html)
        self.assertIn("preset.name === 'Warm Pad'", self.static_html)
        self.assertIn("Explore the preset library", self.static_html)
        self.assertIn("selectors: ['#preset-list']", self.static_html)
        for selector in ("#btn-preview", "#intent-brightness", "#intent-motion",
                         "#intent-space", "#btn-generate", "#btn-share", "#btn-export"):
            self.assertIn(selector, self.static_html)
        self.assertIn("firstGuideIndex === 5) closeFirstGuide(true)", self.static_html)
        self.assertIn("firstGuideIndex === 6) closeFirstGuide(true)", self.static_html)
        self.assertIn("Settings → Deep Dive guide", self.static_html)

    def test_spotlight_is_outside_body_zoom_and_tracks_scroll(self):
        self.assertIn("document.documentElement.appendChild($('first-guide'))", self.static_html)
        self.assertIn("window.addEventListener('scroll', firstGuidePositionHandler, true)", self.static_html)
        self.assertIn("window.removeEventListener('scroll', firstGuidePositionHandler, true)", self.static_html)

    def test_guide_keeps_mantice_typography_outside_body(self):
        self.assertIn(".first-guide { display: none;", self.static_html)
        self.assertIn("font-family: 'Space Mono', monospace", self.static_html)

    def test_mobile_uses_bottom_sheet(self):
        self.assertIn(".first-guide-card { left:0; right:0; top:auto; bottom:0", self.static_html)


if __name__ == "__main__":
    unittest.main()
