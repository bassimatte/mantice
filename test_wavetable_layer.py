import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from engine.wavetable_layer import StreamingWavetableLayer
from engine.web_server import _preset_to_ui_params, _ui_params_to_preset


class WavetableLayerTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
