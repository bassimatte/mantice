import tempfile
import unittest
import base64
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from engine.wavetable_layer import (
    StreamingWavetableLayer,
    wavetable_random_unit,
    wavetable_scan_curve,
    wavetable_smooth_random_curve,
)
import engine.web_server as web_server
from engine.web_server import _preset_to_ui_params, _ui_params_to_preset
from engine.preset_loader import load_preset


class WavetableLayerTests(unittest.TestCase):
    def test_tremor_cartography_showcases_new_wavetable_motion(self):
        preset = load_preset("presets/experimental/Tremor Cartography.yaml")
        wavetable_layers = [layer for layer in preset["layers"] if layer["type"] == "wavetable"]
        self.assertEqual(len(wavetable_layers), 3)
        self.assertIn("smooth_random", {layer["wavetable_scan_mode"] for layer in wavetable_layers})
        self.assertIn("reverse", {layer["wavetable_scan_mode"] for layer in wavetable_layers})
        self.assertTrue(any(layer["wavetable_tremor_amount"] > 0 for layer in wavetable_layers))
        self.assertTrue(any(layer["wavetable_audio_rate_scan"] and layer["wavetable_scan_rate"] > 20 for layer in wavetable_layers))

    def test_scan_shapes_cover_ramps_triangle_and_sine(self):
        phase = np.array([0.0, 0.25, 0.5, 0.75], dtype=np.float32)
        np.testing.assert_allclose(wavetable_scan_curve("forward", phase), [0.0, 0.25, 0.5, 0.75])
        np.testing.assert_allclose(wavetable_scan_curve("reverse", phase), [1.0, 0.75, 0.5, 0.25])
        np.testing.assert_allclose(wavetable_scan_curve("pingpong", phase), [0.0, 0.5, 1.0, 0.5])
        np.testing.assert_allclose(wavetable_scan_curve("sine", phase), [0.0, 0.5, 1.0, 0.5], atol=1e-6)

    def test_smooth_random_is_seeded_bounded_and_continuous(self):
        phase = np.linspace(0.0, 6.0, 12001, dtype=np.float64)
        first = wavetable_smooth_random_curve(phase, seed=42)
        repeated = wavetable_smooth_random_curve(phase, seed=42)
        different = wavetable_smooth_random_curve(phase, seed=43)
        np.testing.assert_array_equal(first, repeated)
        self.assertFalse(np.array_equal(first, different))
        self.assertGreaterEqual(float(first.min()), 0.0)
        self.assertLessEqual(float(first.max()), 1.0)
        self.assertAlmostEqual(float(first[2000]), wavetable_random_unit(42, 1), places=6)
        self.assertLess(float(np.max(np.abs(np.diff(first)))), 0.002)

    def test_smooth_random_scan_is_identical_across_chunk_boundaries(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self._write_table(root)
            cfg = {
                "wavetable_source": "table.wav",
                "wavetable_scan_mode": "smooth_random",
                "wavetable_scan_rate": 2.0,
                "wavetable_scan_start": 0.1,
                "wavetable_scan_end": 0.9,
            }
            whole = StreamingWavetableLayer(cfg, str(root), sample_rate=1000, scan_seed=123)
            chunked = StreamingWavetableLayer(cfg, str(root), sample_rate=1000, scan_seed=123)
            expected = whole._frame_positions(2500)
            actual = np.concatenate([chunked._frame_positions(625) for _ in range(4)])
            np.testing.assert_allclose(actual, expected, atol=1e-6)

    def test_tremor_is_seeded_chunk_continuous_and_range_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self._write_table(root)
            cfg = {
                "wavetable_source": "table.wav",
                "wavetable_scan_mode": "static",
                "wavetable_position": 0.5,
                "wavetable_scan_start": 0.25,
                "wavetable_scan_end": 0.75,
                "wavetable_tremor_amount": 2.0,
                "wavetable_tremor_rate": 2.0,
            }
            whole = StreamingWavetableLayer(cfg, str(root), sample_rate=1000, scan_seed=321)
            chunked = StreamingWavetableLayer(cfg, str(root), sample_rate=1000, scan_seed=321)
            expected = whole._frame_positions(2500)
            actual = np.concatenate([chunked._frame_positions(625) for _ in range(4)])
            np.testing.assert_allclose(actual, expected, atol=1e-6)
            self.assertGreater(float(np.ptp(expected)), 0.5)
            self.assertGreaterEqual(float(expected.min()), 0.25 * 7)
            self.assertLessEqual(float(expected.max()), 0.75 * 7)

    def test_ui_links_to_and_credits_carvetoy(self):
        static_html = Path("engine/static/index.html").read_text(encoding="utf-8")
        docs_html = Path("docs/index.html").read_text(encoding="utf-8")
        self.assertEqual(static_html, docs_html)
        self.assertIn('href="https://www.carvetoy.online/"', static_html)
        self.assertIn("Create ↗", static_html)
        self.assertIn('id="lp-wavetable-library"', static_html)
        self.assertIn('title="Upload a WAV wavetable"', static_html)
        self.assertIn('href="https://freesound.org/search/?q=wavetable"', static_html)
        self.assertIn("Search ↗", static_html)
        self.assertIn("fetch(apiUrl('/api/wavetables'))", static_html)
        self.assertIn('Special thanks to <a href="https://www.carvetoy.online/"', static_html)

    def _write_table(self, root: Path, frames: int = 8) -> None:
        phase = np.arange(2048, dtype=np.float32) / 2048
        waves = []
        for index in range(frames):
            blend = index / max(1, frames - 1)
            waves.append((1 - blend) * np.sin(2 * np.pi * phase) + blend * np.sin(4 * np.pi * phase))
        sf.write(root / "table.wav", np.concatenate(waves), 44100, subtype="FLOAT")

    def test_streams_multiframe_table_continuously(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self._write_table(root)
            layer = StreamingWavetableLayer({
                "wavetable_source": "table.wav",
                "root": 110,
                "voices": 3,
                "wavetable_scan_rate": 0.02,
                "wavetable_scan_mode": "pingpong",
                "amp_min": 0.02,
                "amp_max": 0.04,
            }, str(root), 22050)
            first = layer.next_chunk(2048)
            second = layer.next_chunk(2048)
            self.assertEqual(first.shape, (2048,))
            self.assertTrue(np.isfinite(first).all())
            self.assertGreater(float(np.max(np.abs(first))), 0.001)
            self.assertLess(abs(float(first[-1] - second[0])), 0.2)

    def test_available_wavetables_have_clean_labels_and_frame_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            tables = Path(folder)
            self._write_table(tables, frames=8)
            source = tables / "table.wav"
            source.rename(tables / "ct-wt-1784147249-warpy_cherries-256-2048-32.wav")
            original_tables = web_server._WAVETABLES_DIR
            web_server._WAVETABLES_DIR = tables
            try:
                available = web_server._available_wavetables()
            finally:
                web_server._WAVETABLES_DIR = original_tables
            self.assertEqual(len(available), 1)
            self.assertEqual(available[0]["label"], "Warpy Cherries")
            self.assertEqual(available[0]["frames"], 8)
            self.assertEqual(available[0]["frame_size"], 2048)

    def test_ui_preset_roundtrip_keeps_wavetable_settings(self):
        params = {
            "name": "Wavetable Test",
            "duration": 60,
            "layers": [{
                "name": "Table",
                "type": "wavetable",
                "wavetable_source": "wavetables/test.wav",
                "wavetable_frame_size": 2048,
                "wavetable_frames": 64,
                "wavetable_position": 0.25,
                "wavetable_scan_start": 0.1,
                "wavetable_scan_end": 0.8,
                "wavetable_scan_rate": 0.005,
                "wavetable_scan_mode": "forward",
                "wavetable_tremor_amount": 12,
                "wavetable_tremor_rate": 0.3,
                "wavetable_audio_rate_scan": True,
                "wavetable_detune_cents": 9,
                "wavetable_sha256": "a" * 64,
                "wavetable_source_url": "https://www.carvetoy.online/view/example",
                "wavetable_creator": "Example Artist",
                "wavetable_license": "CC0",
                "root": 82.4,
                "voices": 4,
            }],
        }
        preset = _ui_params_to_preset(params)
        restored = _preset_to_ui_params(preset)["layers"][0]
        self.assertEqual(restored["wavetable_source"], "wavetables/test.wav")
        self.assertEqual(restored["wavetable_frames"], 64)
        self.assertEqual(restored["wavetable_scan_mode"], "forward")
        self.assertAlmostEqual(restored["wavetable_scan_rate"], 0.005)
        self.assertEqual(restored["wavetable_tremor_amount"], 12)
        self.assertAlmostEqual(restored["wavetable_tremor_rate"], 0.3)
        self.assertTrue(restored["wavetable_audio_rate_scan"])
        self.assertEqual(restored["voices"], 4)
        self.assertEqual(restored["wavetable_sha256"], "a" * 64)
        self.assertEqual(restored["wavetable_license"], "CC0")

    def test_scan_range_ui_uses_frame_numbers(self):
        local_html = (Path(__file__).parent / "engine" / "static" / "index.html").read_text()
        deployed_html = (Path(__file__).parent / "docs" / "index.html").read_text()
        for html in (local_html, deployed_html):
            self.assertIn("label: 'Scan Start', min: 0, max: wavetableLastFrame, step: 1", html)
            self.assertIn("label: 'Scan End', min: 0, max: wavetableLastFrame, step: 1", html)
            self.assertIn("displayValue / wavetableLastFrame", html)
            self.assertIn("target.wavetable_frames = data.frames", html)

    def test_scan_rate_ui_is_split_logarithmic_with_cycle_readout(self):
        html = Path("engine/static/index.html").read_text(encoding="utf-8")
        self.assertIn("label: 'Scan Rate', min: 0, max: 1, step: 0.001", html)
        self.assertIn("if (hz <= 1) return (Math.log10(hz) + 3) / 6", html)
        self.assertIn("return 0.5 + 0.5 * Math.log(hz) / Math.log(maxHz)", html)
        self.assertIn("Math.pow(10, -3 + value * 6)", html)
        self.assertIn("Math.pow(maxHz, (value - 0.5) * 2)", html)
        self.assertIn("return `${hzText} Hz · ${duration} cycle`", html)
        self.assertIn("scan-rate-row", html)
        self.assertIn("wavetableAudioRateScan ? 100 : 20", html)
        self.assertIn("Unlock experimental 20–100 Hz", html)

    def test_engine_accepts_twenty_hz_scan_without_leaving_range(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self._write_table(root)
            cfg = {
                "wavetable_source": "table.wav",
                "wavetable_scan_mode": "sine",
                "wavetable_scan_rate": 20.0,
                "wavetable_scan_start": 0.2,
                "wavetable_scan_end": 0.8,
            }
            layer = StreamingWavetableLayer(cfg, str(root), sample_rate=1000, scan_seed=42)
            positions = layer._frame_positions(2000)
            self.assertTrue(np.isfinite(positions).all())
            self.assertGreaterEqual(float(positions.min()), 0.2 * 7 - 1e-5)
            self.assertLessEqual(float(positions.max()), 0.8 * 7 + 1e-5)

    def test_audio_rate_scan_uses_bandlimited_voice_tables(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            phase = np.arange(2048, dtype=np.float32) / 2048
            saw = 2.0 * phase - 1.0
            sf.write(root / "saw.wav", np.tile(saw, 8), 44100, subtype="FLOAT")
            cfg = {
                "wavetable_source": "saw.wav",
                "root": 3000,
                "voices": 1,
                "wavetable_scan_mode": "sine",
                "wavetable_scan_rate": 100.0,
                "wavetable_audio_rate_scan": True,
            }
            layer = StreamingWavetableLayer(cfg, str(root), sample_rate=22050, scan_seed=42)
            harmonic_limit = layer._voice_harmonic_limits[0]
            spectrum = np.abs(np.fft.rfft(layer._voice_tables[0][0]))
            self.assertLess(harmonic_limit, 10)
            self.assertGreater(float(spectrum[1:harmonic_limit + 1].max()), 0.1)
            self.assertLess(float(spectrum[harmonic_limit + 1:].max()), 1e-4)
            audio = layer.next_chunk(4096)
            self.assertTrue(np.isfinite(audio).all())

    def test_scope_data_is_compact_normalized_and_safe(self):
        with tempfile.TemporaryDirectory() as folder:
            samples = Path(folder)
            tables = samples / "wavetables"
            tables.mkdir()
            self._write_table(tables, frames=8)
            original_samples = web_server._SAMPLES_DIR
            web_server._SAMPLES_DIR = samples
            try:
                data = web_server._wavetable_scope_data(
                    "wavetables/table.wav", frame_size=2048, points=64
                )
                self.assertEqual(data["frames"], 8)
                self.assertEqual(data["frame_size"], 2048)
                self.assertEqual(data["points"], 64)
                self.assertEqual(data["waveform_encoding"], "int8-base64")
                packed = np.frombuffer(base64.b64decode(data["waveforms"]), dtype=np.int8)
                self.assertEqual(packed.size, 8 * 64)
                self.assertLessEqual(int(np.max(np.abs(packed.astype(np.int16)))), 127)
                self.assertNotIn("spectrum", data)
                with self.assertRaises(ValueError):
                    web_server._wavetable_scope_data("../private.wav")
            finally:
                web_server._SAMPLES_DIR = original_samples

    def test_scope_is_animated_and_drives_scan_range(self):
        html = Path("engine/static/index.html").read_text(encoding="utf-8")
        self.assertIn('id="wavetable-scope-canvas"', html)
        self.assertIn("/api/wavetables/inspect", html)
        self.assertIn("data.waveform_encoding === 'int8-base64'", html)
        self.assertIn("_wavetableVisualFrame", html)
        self.assertIn("CURRENT FRAME", html)
        self.assertIn("ALL FRAMES · WAVETABLE TERRAIN", html)
        self.assertIn("data._terrainCanvas", html)
        self.assertIn("for (let frame = lastFrame; frame >= 0; frame--)", html)
        self.assertIn("drawTerrainWave(ctx, mixedWave, currentFrame", html)
        self.assertIn("ctx.moveTo(currentX, railY - 7)", html)
        self.assertIn("if (pointerY < railY - 12 || pointerY > railY + 12) return", html)
        self.assertIn("canvas.addEventListener('pointerdown'", html)
        self.assertIn("layer.wavetable_scan_start = startFrame / lastFrame", html)
        self.assertIn("layer.wavetable_scan_end = endFrame / lastFrame", html)
        self.assertIn("if (moved) liveReload()", html)

    def test_ui_offers_the_new_scan_shape_names(self):
        html = Path("engine/static/index.html").read_text(encoding="utf-8")
        self.assertIn('<option value="forward"', html)
        self.assertIn('>Ramp Up</option>', html)
        self.assertIn('<option value="reverse"', html)
        self.assertIn('>Ramp Down</option>', html)
        self.assertIn('>Triangle</option>', html)
        self.assertIn('<option value="sine"', html)
        self.assertIn("mode === 'sine'", html)
        self.assertIn('<option value="smooth_random"', html)
        self.assertIn('>Smooth Random</option>', html)
        self.assertIn("mode === 'smooth_random'", html)
        self.assertIn("id: 'wavetable_tremor_amount'", html)
        self.assertIn("id: 'wavetable_tremor_rate'", html)
        self.assertIn("scanSeed ^ 0xA5A5A5A5", html)

    def test_share_publishes_hashed_asset_and_materializes_it(self):
        with tempfile.TemporaryDirectory() as folder:
            samples = Path(folder)
            source = samples / "wavetables" / "local.wav"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"RIFF-test-wavetable-content")
            preset = {"layers": [{
                "type": "wavetable",
                "wavetable_source": "wavetables/local.wav",
                "wavetable_name": "Local Table",
            }]}
            uploads = []
            original_samples = web_server._SAMPLES_DIR
            web_server._SAMPLES_DIR = samples
            try:
                with patch.object(web_server, "_github_put_content", side_effect=lambda path, content, message, **kwargs: uploads.append((path, content, kwargs))):
                    assets = web_server._publish_shared_wavetables(preset)
                digest = assets[0]["sha256"]
                self.assertEqual(preset["layers"][0]["wavetable_source"], f"shared/wavetables/{digest}.wav")
                self.assertEqual(uploads[0][0], f"shared/wavetables/{digest}.wav")
                self.assertTrue(uploads[0][2]["skip_existing"])

                class FakeResponse:
                    def __enter__(self): return self
                    def __exit__(self, *args): return False
                    def read(self, _limit): return uploads[0][1]

                with patch("urllib.request.urlopen", return_value=FakeResponse()):
                    web_server._materialize_shared_wavetables(preset)
                local_reference = preset["layers"][0]["wavetable_source"]
                self.assertEqual(local_reference, f"wavetables/shared/{digest}.wav")
                self.assertTrue((samples / local_reference).is_file())
            finally:
                web_server._SAMPLES_DIR = original_samples


if __name__ == "__main__":
    unittest.main()
