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

    def test_guide_uses_real_sound_controls(self):
        self.assertIn("const FIRST_GUIDE_STEPS = [", self.static_html)
        self.assertIn("loadFirstGuideClassicStart", self.static_html)
        self.assertIn("preset.name === 'Warm Pad'", self.static_html)
        for selector in ("#btn-preview", "#intent-brightness", "#intent-motion",
                         "#intent-space", "#btn-generate", "#btn-share", "#btn-export"):
            self.assertIn(selector, self.static_html)
        self.assertIn("firstGuideIndex === 4) closeFirstGuide(true)", self.static_html)
        self.assertIn("firstGuideIndex === 5) closeFirstGuide(true)", self.static_html)

    def test_mobile_uses_bottom_sheet(self):
        self.assertIn(".first-guide-card { left:0; right:0; top:auto; bottom:0", self.static_html)


if __name__ == "__main__":
    unittest.main()
