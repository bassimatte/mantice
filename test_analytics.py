import re
import unittest
from pathlib import Path


class AnalyticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.static_html = Path("engine/static/index.html").read_text(encoding="utf-8")
        cls.docs_html = Path("docs/index.html").read_text(encoding="utf-8")

    def test_deployed_and_local_interfaces_are_identical(self):
        self.assertEqual(self.static_html, self.docs_html)

    def test_analytics_is_limited_to_the_canonical_host(self):
        self.assertIn("const MANTICE_ANALYTICS_HOST = 'bassimatte.github.io';", self.static_html)
        self.assertIn("const MANTICE_ANALYTICS_PATH = '/mantice';", self.static_html)
        self.assertIn(
            "location.pathname.startsWith(`${MANTICE_ANALYTICS_PATH}/`)",
            self.static_html,
        )
        self.assertIn("script.dataset.domains = MANTICE_ANALYTICS_HOST;", self.static_html)
        self.assertNotIn("captureOnLocalhost: true", self.static_html)

    def test_umami_uses_the_configured_public_website_id(self):
        self.assertIn(
            "const MANTICE_UMAMI_WEBSITE_ID = 'b2300e0b-bc69-49d7-ad05-06f980b5ed38';",
            self.static_html,
        )
        self.assertIn("const MANTICE_UMAMI_SCRIPT_URL = 'https://cloud.umami.is/script.js';", self.static_html)
        self.assertIn("if (!analyticsIsConfigured()) return false;", self.static_html)
        self.assertIn("script.dataset.websiteId = MANTICE_UMAMI_WEBSITE_ID;", self.static_html)

    def test_umami_tags_all_mantice_traffic(self):
        self.assertIn("const MANTICE_ANALYTICS_TAG = 'mantice';", self.static_html)
        self.assertIn("script.dataset.tag = MANTICE_ANALYTICS_TAG;", self.static_html)

    def test_umami_privacy_controls_are_enabled(self):
        self.assertIn("script.dataset.excludeSearch = 'true';", self.static_html)
        self.assertIn("script.dataset.excludeHash = 'true';", self.static_html)
        self.assertIn("script.dataset.doNotTrack = 'true';", self.static_html)

    def test_visitor_facing_privacy_notice_describes_the_boundary(self):
        self.assertIn('data-tab="tab-privacy"', self.static_html)
        self.assertIn('id="tab-privacy"', self.static_html)
        self.assertIn("Local browser and Python installations", self.static_html)
        self.assertIn("does not use cookies", self.static_html)

    def test_events_and_properties_are_allowlisted(self):
        schema_match = re.search(
            r"const MANTICE_ANALYTICS_SCHEMA = Object\.freeze\(\{(.*?)\n\}\);",
            self.static_html,
            re.DOTALL,
        )
        self.assertIsNotNone(schema_match)
        schema = schema_match.group(1)
        for event in (
            "audio_started",
            "preset_loaded",
            "generator_completed",
            "mutation_completed",
            "gallery_opened",
            "wavetable_action",
            "render_completed",
            "preset_shared",
        ):
            self.assertIn(f"{event}:", schema)
            self.assertRegex(self.static_html, rf"trackUsage\('{event}'")

        self.assertIn("if (typeof window.umami?.track !== 'function') return false;", self.static_html)
        self.assertIn("window.umami.track(eventName, properties);", self.static_html)
        self.assertIn("if (allowed.includes(value)) props[key] = value;", self.static_html)

    def test_sensitive_dynamic_values_are_not_sent(self):
        calls = re.findall(
            r"trackUsage\('([^']+)'\s*,\s*\{(.*?)\}\);",
            self.static_html,
            re.DOTALL,
        )
        self.assertTrue(calls)
        property_text = "\n".join(properties for _, properties in calls)
        for forbidden_key in ("name:", "id:", "query:", "filename:", "params:", "error:"):
            self.assertNotIn(forbidden_key, property_text)


if __name__ == "__main__":
    unittest.main()
