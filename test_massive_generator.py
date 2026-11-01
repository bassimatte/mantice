import asyncio
import itertools
import json
import math
import random
import unittest

import numpy as np
import yaml

from engine.generator import generate_preset, get_available_moods, _compute_cost, _SCALE_INTERVALS
from engine.massive_generator import generate_massive_candidates, ROLES
from engine.preset_loader import load_preset_from_yaml_string
from engine.streaming_engine import StreamingDroneEngine


class MassiveGeneratorTests(unittest.TestCase):
    def test_seeded_family_is_repeatable_and_does_not_change_global_randomness(self):
        before = random.getstate()
        family = generate_massive_candidates(seed=17)
        self.assertEqual(before, random.getstate())
        self.assertEqual(family, generate_massive_candidates(seed=17))
        self.assertNotEqual(family, generate_massive_candidates(seed=18))
        self.assertIn('massive', get_available_moods())
        self.assertEqual(generate_preset('massive', seed=17), family[0])

    def test_every_palette_is_honored_with_a_shared_slow_foundation(self):
        kinds = ['fm', 'subtractive', 'granular', 'wavetable']
        for size in range(1, 5):
            for palette in itertools.combinations(kinds, size):
                family = generate_massive_candidates(21, palette)
                basses = [p['layers'][0]['synthesis'] for p in family]
                self.assertEqual(basses[0], basses[1])
                self.assertEqual(basses[0], basses[2])
                for preset in family:
                    self.assertEqual({layer['type'] for layer in preset['layers']}, set(palette))
                    self.assertLessEqual(_compute_cost(preset['layers']), 500)
                    for layer in preset['layers']:
                        self.assertLessEqual(layer.get('filter_lfo_rate', 0), 0.006)
                        self.assertLessEqual(layer['spatial_motion']['speed'], 0.003)
                    self.assertEqual(preset['layers'][0]['width'], 0)
        for palette in ([], ['invalid']):
            with self.assertRaises(ValueError):
                generate_massive_candidates(1, palette)

    def test_harmonic_roots_and_ratios_stay_in_selected_scale(self):
        for scale, intervals in _SCALE_INTERVALS.items():
            for seed in range(10):
                family = generate_massive_candidates(seed, harmonic_mode=True,
                                                      harmonic_key='D#', harmonic_scale=scale)
                for layer in family[0]['layers']:
                    for ratio in layer['synthesis']['ratios']:
                        midi = round(69 + 12 * math.log2(layer['synthesis']['root'] * ratio / 440))
                        self.assertIn((midi - 3) % 12, intervals)

    def test_all_engines_load_and_render_non_silent_finite_audio(self):
        for kind in ('fm', 'subtractive', 'granular', 'wavetable'):
            for raw in generate_massive_candidates(17, [kind]):
                preset = load_preset_from_yaml_string(yaml.safe_dump(raw))
                engine = StreamingDroneEngine(preset, seed=17, preview_loudness=False)
                chunks = [engine.next_chunk(2048) for _ in range(12)]
                audio = np.concatenate(chunks)
                self.assertTrue(np.isfinite(audio).all(), (kind, raw['meta']['name']))
                self.assertGreater(float(np.max(np.abs(audio))), 1e-5)

    def test_endpoint_returns_three_arrangements_and_shared_preview_seed(self):
        from engine.web_server import generate_endpoint

        class Request:
            async def json(self):
                return {'mood': 'massive', 'seed': 71, 'allowed_types': ['fm', 'subtractive']}

        response = asyncio.run(generate_endpoint(Request()))
        data = json.loads(response.body)
        self.assertTrue(data['ok'])
        self.assertEqual([c['role'] for c in data['candidates']], list(ROLES))
        self.assertEqual({c['seed'] for c in data['candidates']}, {71})
        self.assertEqual(data['params'], data['candidates'][0]['params'])


if __name__ == '__main__':
    unittest.main()
