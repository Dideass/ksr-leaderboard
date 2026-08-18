from __future__ import annotations

import unittest

from ksr_index.config import load_index_config
from ksr_index.normalization import fixed_endpoint_score, normalize_value


class NormalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_index_config("config/index.v1.json")

    def test_multiple_choice_chance_maps_to_zero(self):
        self.assertEqual(fixed_endpoint_score(25, 0.25), 0.0)
        self.assertEqual(fixed_endpoint_score(100, 0.25), 100.0)

    def test_fraction_and_percent_are_equivalent(self):
        self.assertAlmostEqual(fixed_endpoint_score(0.64), 64.0)
        self.assertAlmostEqual(fixed_endpoint_score(64), 64.0)

    def test_omniscience_zero_floor(self):
        spec = self.config.benchmarks["aa_omniscience"]
        self.assertEqual(normalize_value(-12, spec), 0.0)
        self.assertEqual(normalize_value(42, spec), 42.0)

    def test_weights_are_frozen_and_valid(self):
        warnings = self.config.validate()
        self.assertTrue(all(isinstance(item, str) and item for item in warnings))
        total = sum(spec.weight_index for spec in self.config.active())
        self.assertAlmostEqual(total, 1.0)


if __name__ == "__main__":
    unittest.main()
