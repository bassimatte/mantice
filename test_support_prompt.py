import re
import unittest
from pathlib import Path


class SupportPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.static_html = Path("engine/static/index.html").read_text(encoding="utf-8")
        cls.docs_html = Path("docs/index.html").read_text(encoding="utf-8")

    def test_deployed_and_local_interfaces_are_identical(self):
        self.assertEqual(self.static_html, self.docs_html)

    def test_support_links_use_the_shared_canonical_page(self):
        self.assertIn(
            "const MANTICE_SUPPORT_URL = 'https://bassimatte.github.io/support/';",
            self.static_html,
        )
        for element_id in ("support-open", "support-about-link", "btn-support-settings"):
            self.assertIn(f'id="{element_id}"', self.static_html)
        self.assertIn("$(id).href = MANTICE_SUPPORT_URL;", self.static_html)

    def test_prompt_is_limited_to_paid_hosted_work(self):
        self.assertIn("function supportPromptIsHosted()", self.static_html)
        self.assertIn("Boolean(MANTICE_API_BASE)", self.static_html)
        self.assertIn("location.hostname === MANTICE_ANALYTICS_HOST", self.static_html)
        self.assertIn("if (!supportPromptIsHosted()) return null;", self.static_html)
        self.assertIn("['stream', 'segmented', 'journey_stream'].includes(playback)", self.static_html)
        self.assertIn("addSupportUnits((duration / 60) * (hires ? 2 : 1));", self.static_html)

    def test_prompt_frequency_and_opt_out_policy_are_explicit(self):
        for declaration in (
            "const SUPPORT_INITIAL_UNITS = 15;",
            "const SUPPORT_SNOOZE_UNITS = 20;",
            "const SUPPORT_SNOOZE_MS = 14 * 24 * 60 * 60 * 1000;",
            "const SUPPORT_MAX_SHOWS_PER_YEAR = 2;",
        ):
            self.assertIn(declaration, self.static_html)
        self.assertIn("state.optedOut = true;", self.static_html)
        self.assertIn("state.shownAt.length < SUPPORT_MAX_SHOWS_PER_YEAR", self.static_html)
        self.assertIn("state.nextUnits = Math.max(state.nextUnits, state.units + SUPPORT_SNOOZE_UNITS);", self.static_html)

    def test_prompt_is_non_blocking_and_accessible(self):
        self.assertIn('role="dialog" aria-modal="true"', self.static_html)
        self.assertIn('id="support-close" aria-label="Close support request"', self.static_html)
        self.assertIn('id="support-later">Not now</button>', self.static_html)
        self.assertIn('id="support-optout">Don’t ask again</button>', self.static_html)
        self.assertIn("stopAudioAndMaybeSupport", self.static_html)
        self.assertIn("maybeShowSupportPrompt('render');", self.static_html)
        self.assertIn("document.querySelector('.docs-overlay.open, .first-guide.open')", self.static_html)

    def test_local_score_is_not_sent_to_umami(self):
        self.assertIn("const MANTICE_SUPPORT_STATE_KEY = 'mantice_support_v1';", self.static_html)
        self.assertIn("localStorage.setItem(MANTICE_SUPPORT_STATE_KEY", self.static_html)
        self.assertIn("it is never sent to analytics", self.static_html)
        analytics_calls = re.findall(
            r"trackUsage\('support_[^']+'\s*,\s*\{(.*?)\}\);",
            self.static_html,
            re.DOTALL,
        )
        self.assertTrue(analytics_calls)
        self.assertNotIn("units", "\n".join(analytics_calls))
        self.assertIn("support_prompt_shown: { trigger: ['listening', 'render'] }", self.static_html)
        self.assertIn("support_action: { action: ['opened', 'later', 'closed', 'opted_out'] }", self.static_html)
        self.assertIn("support_link_opened: { source: ['prompt', 'about', 'settings'] }", self.static_html)

    def test_every_support_interaction_has_an_analytics_event(self):
        self.assertIn("trackUsage('support_prompt_shown', { trigger });", self.static_html)
        self.assertIn("trackUsage('support_action', { action });", self.static_html)
        self.assertIn("trackUsage('support_link_opened', { source: 'prompt' });", self.static_html)
        self.assertIn("trackUsage('support_link_opened', { source: 'about' });", self.static_html)
        self.assertIn("trackUsage('support_link_opened', { source: 'settings' });", self.static_html)
        self.assertIn("$('support-close').addEventListener('click', () => deferSupportPrompt('closed'));", self.static_html)
        self.assertIn("$('support-later').addEventListener('click', () => deferSupportPrompt('later'));", self.static_html)
        self.assertIn("$('support-optout').addEventListener('click', () => deferSupportPrompt('opted_out'));", self.static_html)
        self.assertIn("deferSupportPrompt('opened');", self.static_html)


if __name__ == "__main__":
    unittest.main()
