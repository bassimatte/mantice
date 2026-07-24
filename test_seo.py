import json
import re
import struct
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


class SeoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.static_html = Path("engine/static/index.html").read_text(encoding="utf-8")
        cls.docs_html = Path("docs/index.html").read_text(encoding="utf-8")

    def test_deployed_and_local_metadata_are_identical(self):
        self.assertEqual(self.static_html, self.docs_html)

    def test_homepage_has_search_and_social_metadata(self):
        html = self.docs_html
        self.assertIn("<title>Mantice — Free Online Ambient Drone Synthesizer</title>", html)
        self.assertIn('<meta name="description"', html)
        self.assertIn('<link rel="canonical" href="https://bassimatte.github.io/mantice/">', html)
        self.assertIn('<meta property="og:image" content="https://bassimatte.github.io/mantice/social-card.png">', html)
        self.assertIn('<meta name="twitter:card" content="summary_large_image">', html)
        self.assertIn("free, open-source online ambient drone synthesizer", html)

    def test_software_application_structured_data_is_valid_json(self):
        match = re.search(
            r'<script type="application/ld\+json">\s*(.*?)\s*</script>',
            self.docs_html,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        data = json.loads(match.group(1))
        self.assertEqual(data["@type"], "SoftwareApplication")
        self.assertEqual(data["url"], "https://bassimatte.github.io/mantice/")
        self.assertEqual(data["offers"]["price"], "0")

    def test_crawl_files_point_to_the_canonical_homepage(self):
        robots = Path("docs/robots.txt").read_text(encoding="utf-8")
        self.assertIn("User-agent: *", robots)
        self.assertIn("Allow: /", robots)
        self.assertIn("Sitemap: https://bassimatte.github.io/mantice/sitemap.xml", robots)
        root = ET.parse("docs/sitemap.xml").getroot()
        namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locations = {
            node.text for node in root.findall("s:url/s:loc", namespace)
        }
        self.assertEqual(locations, {
            "https://bassimatte.github.io/mantice/",
            "https://bassimatte.github.io/mantice/presets/",
            "https://bassimatte.github.io/mantice/learn/ambient-drone-synthesis.html",
            "https://bassimatte.github.io/mantice/learn/wavetable-drone.html",
        })

    def test_discovery_pages_are_semantic_unique_and_internally_linked(self):
        pages = (
            "docs/presets/index.html",
            "docs/learn/ambient-drone-synthesis.html",
            "docs/learn/wavetable-drone.html",
        )
        titles = set()
        for filename in pages:
            html = Path(filename).read_text(encoding="utf-8")
            title = re.search(r"<title>([^<]+)</title>", html)
            canonical = re.search(r'<link rel="canonical" href="([^"]+)">', html)
            self.assertIsNotNone(title, filename)
            self.assertIsNotNone(canonical, filename)
            self.assertNotIn(title.group(1), titles)
            titles.add(title.group(1))
            self.assertIn('<meta name="description"', html)
            self.assertIn('type="application/ld+json"', html)
            structured = re.search(
                r'<script type="application/ld\+json">\s*(.*?)\s*</script>',
                html,
                re.DOTALL,
            )
            json.loads(structured.group(1))

        self.assertIn('href="https://bassimatte.github.io/mantice/presets/"', self.docs_html)
        self.assertIn('href="https://bassimatte.github.io/mantice/learn/ambient-drone-synthesis.html"', self.docs_html)
        self.assertIn('href="https://bassimatte.github.io/mantice/learn/wavetable-drone.html"', self.docs_html)

    def test_social_card_is_1200_by_630(self):
        docs_card = Path("docs/social-card.png").read_bytes()
        static_card = Path("engine/static/social-card.png").read_bytes()
        self.assertEqual(docs_card, static_card)
        self.assertEqual(docs_card[:8], b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", docs_card[16:24])
        self.assertEqual((width, height), (1200, 630))


if __name__ == "__main__":
    unittest.main()
