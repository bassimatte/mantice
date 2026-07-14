import unittest

import numpy as np
from scipy.signal import resample_poly

from engine.post_processing import TRUE_PEAK_CEILING, final_limit_normalize


class FinalLimitNormalizeTests(unittest.TestCase):
    def test_hot_audio_is_attenuated_to_minus_one_db_true_peak(self):
        phase = np.linspace(0.0, 20.0 * np.pi, 2205, endpoint=False)
        mono = (1.25 * np.sin(phase)).astype(np.float32)
        audio = np.column_stack((mono, mono))

        limited = final_limit_normalize(audio)
        true_peak = float(np.max(np.abs(resample_poly(limited, 4, 1, axis=0))))

        self.assertLessEqual(true_peak, TRUE_PEAK_CEILING + 1e-5)
        self.assertLess(float(np.max(np.abs(limited))), float(np.max(np.abs(audio))))

    def test_quiet_audio_is_not_boosted(self):
        audio = np.full((128, 2), 0.25, dtype=np.float32)
        limited = final_limit_normalize(audio)

        np.testing.assert_array_equal(limited, audio)

    def test_empty_audio_is_accepted(self):
        audio = np.empty((0, 2), dtype=np.float32)
        limited = final_limit_normalize(audio)

        self.assertEqual(limited.shape, audio.shape)
        self.assertEqual(limited.dtype, audio.dtype)


if __name__ == "__main__":
    unittest.main()
