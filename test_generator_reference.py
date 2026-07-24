import unittest

from generator_reference import verify


class GeneratorReferenceTests(unittest.TestCase):
    def test_fixed_seed_reference_candidates(self):
        self.assertEqual(verify(), [])


if __name__ == "__main__":
    unittest.main()
