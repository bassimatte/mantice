import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from engine.wavetable_layer import StreamingWavetableLayer
import engine.web_server as web_server
from engine.web_server import _preset_to_ui_params, _ui_params_to_preset


class WavetableLayerTests(unittest.TestCase):
    def test_ui_links_to_and_credits_carvetoy(self):
        static_html = Path("engine/static/index.html").read_text(encoding="utf-8")
        docs_html = Path("docs/index.html").read_text(encoding="utf-8")
        self.assertEqual(static_html, docs_html)
        self.assertIn('href="https://www.carvetoy.online/"', static_html)
        self.assertIn("Get wavetables ↗", static_html)
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

    def test_ui_preset_roundtrip_keeps_wavetable_settings(self):
        params = {
            "name": "Wavetable Test",
            "duration": 60,
            "layers": [{
                "name": "Table",
                "type": "wavetable",
                "wavetable_source": "wavetables/test.wav",
                "wavetable_frame_size": 2048,
                "wavetable_position": 0.25,
                "wavetable_scan_start": 0.1,
                "wavetable_scan_end": 0.8,
                "wavetable_scan_rate": 0.005,
                "wavetable_scan_mode": "forward",
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
        self.assertEqual(restored["wavetable_scan_mode"], "forward")
        self.assertAlmostEqual(restored["wavetable_scan_rate"], 0.005)
        self.assertEqual(restored["voices"], 4)
        self.assertEqual(restored["wavetable_sha256"], "a" * 64)
        self.assertEqual(restored["wavetable_license"], "CC0")

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
