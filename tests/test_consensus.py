from __future__ import annotations

import unittest

from scipy.special import expit

from ksr_index.config import load_index_config
from ksr_index.consensus import score_consensus, select_model_observations

from helpers import observation


class ConsensusScoringTests(unittest.TestCase):
    def setUp(self):
        self.config = load_index_config("config/index.v1.json")
        self.anchor_ids = self.config.settings["anchors"][:6]
        self.benchmarks = [
            "hle",
            "critpt",
            "livebench_reasoning",
            "livebench_data_analysis",
            "aa_omniscience",
        ]

    def model_rows(self, family_id: str, score: float):
        return [
            observation(
                benchmark_id,
                score,
                model_id=family_id.replace("/", "-"),
                family_id=family_id,
                provider=family_id.split("/", 1)[0],
            )
            for benchmark_id in self.benchmarks
        ]

    def complete_fixture(self):
        rows = []
        for index, anchor in enumerate(self.anchor_ids):
            rows.extend(self.model_rows(anchor, 45 + index * 5))
        rows.extend(self.model_rows("lab/model-high", 86))
        rows.extend(self.model_rows("lab/model-low", 34))
        return rows

    def test_fixed_single_index_weights_sum_to_one(self):
        self.assertAlmostEqual(
            sum(spec.weight_index for spec in self.config.active()), 1.0
        )
        self.assertTrue(all(spec.weight_index <= 0.15 for spec in self.config.active()))

    def test_v3_basket_is_exact_and_aa_native_share_is_capped(self):
        active = {spec.id: spec for spec in self.config.active()}
        self.assertEqual(
            set(active),
            {
                "hle", "gpqa_diamond", "mmlu_pro", "critpt",
                "livebench_math", "livebench_reasoning",
                "livebench_data_analysis", "aa_lcr",
                "aa_omniscience", "arc_agi_2",
            },
        )
        self.assertTrue(
            all(
                abs(round(spec.weight_index * 100) / 100 - spec.weight_index) < 1e-12
                and abs((spec.weight_index * 100) % 5) < 1e-9
                for spec in active.values()
            )
        )
        self.assertAlmostEqual(
            sum(active[benchmark_id].weight_index for benchmark_id in {
                "critpt", "aa_lcr", "aa_omniscience"
            }),
            0.30,
        )

    def test_one_family_appears_once_and_order_recovers_signal(self):
        result = score_consensus(self.complete_fixture(), self.config)
        ranked = [row for row in result.rows if row.status == "ranked"]
        self.assertEqual(len({row.entity_id for row in result.rows}), len(result.rows))
        high = next(row for row in ranked if row.entity_id == "lab/model-high")
        low = next(row for row in ranked if row.entity_id == "lab/model-low")
        self.assertLess(high.rank, low.rank)
        self.assertGreater(high.point, low.point)
        self.assertEqual(result.diagnostics["missing_policy"], "no_imputation_no_penalty_no_weight_transfer")

    def test_highest_reasoning_effort_wins_without_score_peeking(self):
        medium = observation(
            "hle", 99, family_id="lab/model", effort="medium", source_id="medium"
        )
        high = observation(
            "hle", 61, family_id="lab/model", effort="high", source_id="high"
        )
        selected = select_model_observations([medium, high], self.config)
        chosen = selected["lab/model"]["hle"]
        self.assertEqual(chosen.observation.reasoning_effort, "high")
        self.assertAlmostEqual(chosen.score, 61.0)

    def test_missing_benchmark_stays_blank_and_model_is_not_ranked(self):
        rows = self.complete_fixture()
        rows.append(
            observation(
                "hle",
                95,
                family_id="lab/one-benchmark-only",
                model_id="one-benchmark-only",
            )
        )
        result = score_consensus(rows, self.config)
        profile = next(
            row for row in result.rows if row.entity_id == "lab/one-benchmark-only"
        )
        self.assertEqual(profile.status, "insufficient")
        self.assertIsNone(profile.point)
        self.assertFalse(profile.components["livebench_reasoning"]["observed"])
        self.assertIsNone(profile.components["livebench_reasoning"]["score"])
        self.assertAlmostEqual(profile.coverage, 0.15)

    def test_full_coverage_is_high_confidence(self):
        benches = [spec.id for spec in self.config.active()]

        def all_benches(family_id: str, score: float):
            return [
                observation(
                    benchmark_id,
                    score,
                    model_id=family_id.replace("/", "-"),
                    family_id=family_id,
                    provider=family_id.split("/", 1)[0],
                )
                for benchmark_id in benches
            ]

        rows = []
        for index, anchor in enumerate(self.anchor_ids):
            rows.extend(all_benches(anchor, 45 + index * 5))
        rows.extend(all_benches("lab/complete", 92))
        result = score_consensus(rows, self.config)
        complete = next(row for row in result.rows if row.entity_id == "lab/complete")
        self.assertEqual(complete.status, "ranked")
        self.assertAlmostEqual(complete.coverage, 1.0)
        self.assertEqual(complete.observed_benchmarks, len(benches))
        self.assertEqual(complete.confidence, "high")

    def test_anchor_score_excludes_self_comparison(self):
        result = score_consensus(self.complete_fixture(), self.config)
        anchors = [
            row
            for row in result.rows
            if row.entity_id in self.anchor_ids and row.latent_ability is not None
        ]
        target = next(row for row in anchors if row.entity_id == self.anchor_ids[-1])
        others = [row for row in anchors if row.entity_id != target.entity_id]
        expected = 100.0 * sum(
            float(expit(target.latent_ability - row.latent_ability))
            for row in others
        ) / len(others)
        self.assertAlmostEqual(target.point, expected, places=6)
        buggy = (
            100.0
            * (
                0.5
                + sum(
                    float(expit(target.latent_ability - row.latent_ability))
                    for row in others
                )
            )
            / (len(others) + 1)
        )
        self.assertGreater(abs(target.point - buggy), 0.05)


if __name__ == "__main__":
    unittest.main()
