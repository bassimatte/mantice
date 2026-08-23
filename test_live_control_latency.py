"""Regression checks for responsive browser live controls."""

from copy import deepcopy
from pathlib import Path
import unittest

import numpy as np

from engine.preset_loader import load_preset
from engine.streaming_engine import StreamingDroneEngine


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

    def test_browser_routes_safe_changes_through_patch_protocol(self):
        self.assertIn("function canLivePatch(previous, next)", self.html)
        self.assertIn("action: 'patch'", self.html)
        self.assertIn("msg.status === 'reload_required'", self.html)
        self.assertIn('elif action == "patch":', self.server)

    def test_layer_meters_use_the_current_preview_websocket(self):
        self.assertNotIn("fetch('/api/meters')", self.html)
        self.assertIn("function updateLayerMeters(layers = [])", self.html)
        self.assertIn("msg.status === 'meters'", self.html)
        self.assertIn('"status": "meters"', self.server)
        self.assertIn('"layers": engine.get_peak_meters()', self.server)

    def test_mobile_attempts_live_stream_before_segmented_fallback(self):
        preview_start = self.html.index("async function doPreview(options = {})")
        preview_body = self.html[preview_start:preview_start + 2600]
        self.assertNotIn("if (isMobile()) { return doPreviewSegmented(); }", preview_body)
        self.assertIn("new WebSocket(wsUrl('/ws/preview'))", preview_body)
        self.assertIn("_startMobileStartupTimer(previewSocket)", preview_body)
        self.assertIn("const _MOBILE_WS_STARTUP_TIMEOUT_MS = 8000;", self.html)
        self.assertIn("const _MOBILE_WS_MAX_RECONNECTS = 1;", self.html)
        self.assertIn("function createStreamingAudioContext()", self.html)
        self.assertIn("return new AudioContextClass();", self.html)

    def test_mobile_stream_failure_has_segmented_compatibility_mode(self):
        self.assertIn("function _fallbackToSegmented(reason = 'network')", self.html)
        self.assertIn("registerPlaybackFailed('stream', reason)", self.html)
        self.assertIn("doPreviewSegmented({ fallback: true, seed });", self.html)
        self.assertIn("Compatibility mode — buffering…", self.html)
        self.assertIn("▶ Playing — compatibility mode", self.html)
        self.assertIn(
            "ws.onerror = () => _handlePreviewConnectionFailure(previewSocket)",
            self.html,
        )
        self.assertIn(
            "ws.onclose = () => _handlePreviewConnectionFailure(previewSocket)",
            self.html,
        )

    def test_first_mobile_audio_cancels_startup_fallback(self):
        message_start = self.html.index("ws.onmessage = (event) =>")
        message_body = self.html[message_start:message_start + 1500]
        self.assertIn("_mobileReceivedAudio = true", message_body)
        self.assertIn("_clearMobileStartupTimer()", message_body)

    def test_segmented_fallback_rebuffers_live_edits_safely(self):
        reload_start = self.html.index("function liveReload(crossfadeOverride = null)")
        reload_body = self.html[reload_start:reload_start + 1900]
        self.assertIn("if (_segPlaying)", reload_body)
        self.assertIn("doPreviewSegmented({ fallback: true, seed });", reload_body)
        self.assertIn("segmentSession !== _segSession", self.html)

    def test_engine_patches_controls_without_rebuilding_synth_layers(self):
        preset = load_preset(ROOT / "presets" / "essentials" / "Simple Drone.yaml")
        engine = StreamingDroneEngine(preset, seed=42, preview_loudness=False)
        layer_ids = [id(layer) for layer in engine.layers]

        patched = deepcopy(engine.preset)
        layer = patched["layers"][0]
        layer.update({
            "muted": True,
            "volume_db": -6.0,
            "pan": 0.75,
            "width": 1.4,
            "filter_type": "lp",
            "filter_cutoff": 900.0,
            "filter_resonance": 2.0,
            "chorus_mix": 0.25,
            "flanger_wet": 0.2,
            "phaser_wet": 0.15,
            "distortion_drive": 0.4,
        })
        patched["master"]["output_gain_db"] = -2.0

        accepted, reason = engine.queue_live_controls(patched, ramp_ms=50.0)
        self.assertTrue(accepted, reason)
        chunk = engine.next_chunk(1024)

        self.assertTrue(np.isfinite(chunk).all())
        self.assertEqual(layer_ids, [id(layer) for layer in engine.layers])
        self.assertIsNone(engine._old_engine)
        self.assertEqual(engine.filters[0].filter_type, "lp")
        self.assertAlmostEqual(engine.filters[0].base_cutoff, 900.0)
        self.assertAlmostEqual(engine.panners[0].base_pan, 0.875)
        self.assertAlmostEqual(engine.panners[0].width, 1.4)
        self.assertAlmostEqual(engine.choruses[0].mix, 0.25)
        self.assertAlmostEqual(engine.flangers[0].wet, 0.2)
        self.assertAlmostEqual(engine.phasers[0].wet, 0.15)
        self.assertAlmostEqual(engine._layer_control_target[0], 0.0)
        self.assertAlmostEqual(engine._master._output_gain, 10.0 ** (-2.0 / 20.0))

        # The 50 ms mute ramp completes within two 1024-sample chunks at 22.05 kHz.
        engine.next_chunk(1024)
        self.assertAlmostEqual(engine._layer_control_gain[0], 0.0)

        unmuted = deepcopy(engine.preset)
        unmuted["layers"][0]["muted"] = False
        accepted, reason = engine.queue_live_controls(unmuted, ramp_ms=50.0)
        self.assertTrue(accepted, reason)
        engine.next_chunk(1024)
        engine.next_chunk(1024)
        self.assertGreater(engine._layer_control_gain[0], 0.49)

    def test_layer_mix_patch_supports_every_synthesis_engine(self):
        preset_paths = [
            ROOT / "presets" / "experimental" / "Gear Meditation.yaml",
            ROOT / "presets" / "experimental" / "Chopper Siege Engine.yaml",
        ]
        observed_types = set()
        for preset_path in preset_paths:
            preset = load_preset(preset_path)
            preset["reverb"] = None
            engine = StreamingDroneEngine(
                preset, seed=42, preview_loudness=False
            )
            layer_ids = [id(layer) for layer in engine.layers]
            observed_types.update(
                cfg.get("type", "fm")
                for cfg in engine.preset["layers"]
                if not cfg.get("muted", False)
            )
            patched = deepcopy(engine.preset)
            for layer in patched["layers"]:
                layer["muted"] = True

            accepted, reason = engine.queue_live_controls(patched)
            self.assertTrue(accepted, reason)
            chunk = engine.next_chunk(1024)
            self.assertTrue(np.isfinite(chunk).all())
            self.assertEqual(layer_ids, [id(layer) for layer in engine.layers])

        self.assertTrue(
            {"fm", "subtractive", "granular", "wavetable"}.issubset(observed_types)
        )

    def test_structural_changes_require_reload(self):
        preset = load_preset(ROOT / "presets" / "essentials" / "Simple Drone.yaml")
        engine = StreamingDroneEngine(preset, seed=42, preview_loudness=False)
        changed = deepcopy(engine.preset)
        changed["layers"][0]["root"] *= 2.0

        accepted, reason = engine.queue_live_controls(changed)
        self.assertFalse(accepted)
        self.assertEqual(reason, "structural_change")

    def test_initially_muted_layer_uses_reload_when_first_unmuted(self):
        preset = load_preset(ROOT / "presets" / "essentials" / "Simple Drone.yaml")
        preset["layers"][0]["muted"] = True
        engine = StreamingDroneEngine(preset, seed=42, preview_loudness=False)
        changed = deepcopy(engine.preset)
        changed["layers"][0]["muted"] = False

        accepted, reason = engine.queue_live_controls(changed)
        self.assertFalse(accepted)
        self.assertEqual(reason, "inactive_layer_requires_reload")


if __name__ == "__main__":
    unittest.main()
