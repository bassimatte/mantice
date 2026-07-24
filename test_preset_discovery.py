import unittest

from engine.preset_discovery import summarize_preset


class PresetDiscoveryTests(unittest.TestCase):
    def test_summary_derives_stable_search_traits_and_fingerprint(self):
        summary = summarize_preset({
            "duration": 90,
            "tuning_mode": "ji",
            "tuning_system_ji": "7limit_ji",
            "layers": [
                {
                    "name": "Floor",
                    "type": "wavetable",
                    "root": 55,
                    "volume_db": -4.25,
                    "width": 1.4,
                    "spatial_motion": {
                        "trajectory_x": "orbit",
                        "speed": 0.003,
                    },
                },
                {"name": "Air", "type": "fm", "root": 220, "width": 1.2},
            ],
            "reverb": {"enabled": True, "wet": 0.42},
            "shimmer": {"wet": 0.1},
            "binaural": {"enabled": True},
        })

        self.assertEqual(summary["layer_count"], 2)
        self.assertEqual(summary["lowest_hz"], 55.0)
        self.assertEqual(summary["synth_types"], ["wavetable", "fm"])
        self.assertEqual(
            summary["traits"],
            ["wavetable", "fm", "sub-heavy", "wide", "motion", "deep space"],
        )
        self.assertEqual(summary["tuning"], "7limit_ji")
        self.assertEqual(summary["reverb_mix"], 0.42)
        self.assertEqual(summary["fingerprint"][0]["trajectory"], "orbit")

    def test_invalid_params_return_empty_summary(self):
        self.assertEqual(summarize_preset(None), {})


if __name__ == "__main__":
    unittest.main()
