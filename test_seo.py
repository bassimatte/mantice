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
        self.assertIn(
            '<meta name="google-site-verification" '
            'content="pp3jhptIHkhnjku-p-0sm3J4XAJzQlE7WiNZ2JwKUNA">',
            html,
        )
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
        self.assertEqual(data["author"]["url"], "https://bassimatte.github.io/")
        self.assertEqual(
            data["author"]["sameAs"],
            [
                "https://github.com/bassimatte",
                "https://freesound.org/people/bassimat/",
            ],
        )

    def test_creator_links_use_the_canonical_homepage(self):
        self.assertIn('class="creator-link" href="https://bassimatte.github.io/"', self.docs_html)
        self.assertIn(".creator-link:focus-visible", self.docs_html)
        self.assertIn("More tools by Matteo Bassi ↗", self.docs_html)
        self.assertIn('href="https://bassimatte.github.io/#instruments"', self.docs_html)
        self.assertIn("Source code ↗", self.docs_html)

    def test_visible_about_section_explains_the_instrument(self):
        html = self.docs_html
        about_index = html.index('id="about-mantice-title"')
        self.assertGreater(about_index, html.index('id="journey-card"'))
        self.assertLess(about_index, html.index("</main>"))
        for text in (
            "About the instrument",
            "What Mantice creates",
            "How it works",
            "What you can use it for",
            "Listen to Mantice sounds ↗",
            "Support Mantice ↗",
            "View source ↗",
            "More tools by Matteo Bassi ↗",
        ):
            self.assertIn(text, html)
        self.assertIn('href="https://bassimatte.github.io/support/"', html)

    def test_crawl_files_point_to_the_canonical_homepage(self):
        robots = Path("docs/robots.txt").read_text(encoding="utf-8")
        self.assertIn("User-agent: *", robots)
        self.assertIn("Allow: /", robots)
        self.assertIn("Sitemap: https://bassimatte.github.io/mantice/sitemap.xml", robots)
        root = ET.parse("docs/sitemap.xml").getroot()
        namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        self.assertEqual(
            root.findtext("s:url/s:loc", namespaces=namespace),
            "https://bassimatte.github.io/mantice/",
        )

    def test_social_card_is_1200_by_630(self):
        docs_card = Path("docs/social-card.png").read_bytes()
        static_card = Path("engine/static/social-card.png").read_bytes()
        self.assertEqual(docs_card, static_card)
        self.assertEqual(docs_card[:8], b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", docs_card[16:24])
        self.assertEqual((width, height), (1200, 630))

    def test_icon_assets_are_deployed_at_the_expected_sizes(self):
        self.assertIn('<link rel="apple-touch-icon" href="mantice-icon.png">', self.docs_html)

        for filename, expected_size in (("mantice-icon.png", (512, 512)), ("favicon.png", (32, 32))):
            docs_icon = Path("docs", filename).read_bytes()
            static_icon = Path("engine/static", filename).read_bytes()
            self.assertEqual(docs_icon, static_icon)
            self.assertEqual(docs_icon[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", docs_icon[16:24]), expected_size)

        self.assertEqual(
            Path("docs/favicon.ico").read_bytes(),
            Path("engine/static/favicon.ico").read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
