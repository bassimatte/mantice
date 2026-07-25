import unittest

import numpy as np
from scipy.signal import resample_poly

from engine.post_processing import (
    LIVE_PEAK_CEILING,
    MAX_LOUDNESS_GAIN_DB,
    TRUE_PEAK_CEILING,
    StreamingLoudnessController,
    final_limit_normalize,
    integrated_loudness,
    loudness_normalize,
)


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

    def test_integrated_loudness_tracks_signal_level(self):
        sr = 22050
        phase = np.arange(sr * 2) * (2.0 * np.pi * 1000.0 / sr)
        quiet = np.column_stack((0.02 * np.sin(phase), 0.02 * np.sin(phase))).astype(np.float32)
        loud = quiet * 10.0

        difference = integrated_loudness(loud, sr) - integrated_loudness(quiet, sr)

        self.assertAlmostEqual(difference, 20.0, delta=0.15)

    def test_loudness_normalization_caps_upward_gain_and_true_peak(self):
        sr = 22050
        phase = np.arange(sr * 2) * (2.0 * np.pi * 1000.0 / sr)
        mono = (0.002 * np.sin(phase)).astype(np.float32)
        audio = np.column_stack((mono, mono))

        normalized = loudness_normalize(audio, sr)
        gain_db = 20.0 * np.log10(
            np.sqrt(np.mean(normalized ** 2)) / np.sqrt(np.mean(audio ** 2))
        )
        true_peak = float(np.max(np.abs(resample_poly(normalized, 4, 1, axis=0))))

        self.assertAlmostEqual(gain_db, MAX_LOUDNESS_GAIN_DB, delta=0.1)
        self.assertLessEqual(true_peak, TRUE_PEAK_CEILING + 1e-5)

    def test_streaming_controller_boosts_quiet_audio_without_exceeding_ceiling(self):
        sr = 22050
        phase = np.arange(2048) * (2.0 * np.pi * 440.0 / sr)
        mono = (0.02 * np.sin(phase)).astype(np.float32)
        audio = np.column_stack((mono, mono))
        controller = StreamingLoudnessController(sr)

        processed = controller.process(audio)

        self.assertGreater(np.sqrt(np.mean(processed ** 2)), np.sqrt(np.mean(audio ** 2)) * 1.9)
        self.assertLessEqual(float(np.max(np.abs(processed))), LIVE_PEAK_CEILING + 1e-6)


if __name__ == "__main__":
    unittest.main()
