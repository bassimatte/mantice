import unittest
import warnings

import numpy as np

from engine.streaming_engine import StreamingFDNReverb


class FDNIntegrityTests(unittest.TestCase):
    def test_feedback_mix_is_warning_free_and_finite(self):
        reverb = StreamingFDNReverb({
            "enabled": True,
            "space": "plate",
            "mix": 0.5,
            "decay_trim": 1.0,
        }, sample_rate=22050)
        impulse = np.zeros((2048, 2), dtype=np.float32)
        impulse[0] = 0.9

        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            chunks = [reverb.next_chunk(impulse)]
            for _ in range(40):
                chunks.append(reverb.next_chunk(np.zeros_like(impulse)))

        audio = np.concatenate(chunks)
        self.assertTrue(np.isfinite(audio).all())
        self.assertTrue(np.isfinite(reverb.buf).all())
        self.assertLessEqual(float(np.max(np.abs(reverb.buf))), reverb._STATE_LIMIT)

    def test_non_finite_input_and_state_are_recovered(self):
        reverb = StreamingFDNReverb({
            "enabled": True,
            "space": "cathedral",
            "mix": 0.7,
            "decay_trim": 1.0,
        }, sample_rate=22050)
        reverb.buf[0, 0] = np.nan
        broken = np.zeros((1024, 2), dtype=np.float32)
        broken[0, 0] = np.inf
        broken[1, 1] = np.nan

        output = reverb.next_chunk(broken)

        self.assertTrue(np.isfinite(output).all())
        self.assertTrue(np.isfinite(reverb.buf).all())


if __name__ == "__main__":
    unittest.main()
