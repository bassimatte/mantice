import unittest
from pathlib import Path


class MonitorVolumeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parent
        cls.local_html = (root / "engine/static/index.html").read_text(encoding="utf-8")
        cls.deployed_html = (root / "docs/index.html").read_text(encoding="utf-8")

    def test_local_and_deployed_controls_match(self):
        self.assertEqual(self.local_html, self.deployed_html)

    def test_monitor_is_persistent_and_separate_from_preset_parameters(self):
        self.assertIn("mantice_monitor_volume_db_v1", self.local_html)
        self.assertIn("mantice_monitor_muted_v1", self.local_html)
        self.assertIn("function initMonitorVolume()", self.local_html)
        collect_params = self.local_html.split("function collectParams()", 1)[1].split(
            "// ── Rendered Audio Playback", 1
        )[0]
        self.assertNotIn("monitorVolume", collect_params)
        self.assertNotIn("data-monitor-volume", collect_params)

    def test_desktop_and_mobile_have_accessible_controls(self):
        self.assertGreaterEqual(self.local_html.count("data-monitor-volume"), 2)
        self.assertIn("monitor-volume monitor-desktop", self.local_html)
        self.assertIn("monitor-volume monitor-mobile", self.local_html)
        self.assertEqual(self.local_html.count('aria-label="Monitor volume"'), 2)
        self.assertIn("Listening volume only — presets and downloads are unchanged", self.local_html)

    def test_every_mantice_browser_playback_path_uses_monitor_output(self):
        expected_connections = (
            "analyser.connect(monitorInputFor(playbackCtx))",
            "startupGain.connect(monitorInputFor(streamingCtx))",
            "segmentAnalyser.connect(monitorInputFor(_segCtx))",
            "source.connect(monitorInputFor(context))",
            "source.connect(monitorInputFor(ctx))",
        )
        for connection in expected_connections:
            self.assertIn(connection, self.local_html)
        self.assertIn("limiter.connect(meter)", self.local_html)
        self.assertIn("meter.connect(context.destination)", self.local_html)
        self.assertIn("limiter.threshold.value = -1", self.local_html)
        self.assertIn("limiter.ratio.value = 20", self.local_html)

    def test_live_changes_are_smoothed_and_boost_is_visually_marked(self):
        self.assertIn("setTargetAtTime(target, output.context.currentTime, 0.015)", self.local_html)
        self.assertIn("control.classList.toggle('boosted'", self.local_html)
        self.assertIn('min="-40" max="6" step="1"', self.local_html)

    def test_small_post_monitor_peak_meter_has_accessible_level_feedback(self):
        self.assertEqual(self.local_html.count('aria-label="Monitor output level"'), 2)
        self.assertIn("function drawMonitorLevel()", self.local_html)
        self.assertIn("output.meter.getFloatTimeDomainData(output.meterData)", self.local_html)
        self.assertIn("monitorDisplayedPeak * 0.88", self.local_html)
        self.assertIn("level.classList.toggle('hot', db >= -3)", self.local_html)
        self.assertIn("decibels full scale", self.local_html)


if __name__ == "__main__":
    unittest.main()
