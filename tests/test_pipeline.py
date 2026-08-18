from __future__ import annotations

import unittest
from pathlib import Path

from ksr_index.cli import _add_score
from ksr_index.config import load_index_config
from ksr_index.pipeline import build_artifacts
from ksr_index.site import short_name
from ksr_index.storage import merge_observations

from helpers import observation


class PipelineTests(unittest.TestCase):
    def test_short_name_strips_parenthetical_config(self):
        self.assertEqual(short_name("GPT-5.6 Sol (max)"), "GPT-5.6 Sol")
        self.assertEqual(
            short_name("Claude Fable 5 (Adaptive Reasoning, Max Effort, Opus 4.8 Fallback)"),
            "Claude Fable 5",
        )
        self.assertEqual(short_name("Qwen3.8 Max"), "Qwen3.8 Max")

    def test_observation_identity_preserves_reasoning_effort(self):
        default = observation("hle_text", 20, effort="default")
        high = observation("hle_text", 30, effort="high")
        self.assertEqual(len(merge_observations([default], [high])), 2)

    def test_empty_build_is_an_explicit_preview(self):
        root = Path("artifacts/test-pipeline")
        (root / "artifacts/data").mkdir(parents=True, exist_ok=True)
        config = load_index_config("config/index.v1.json")
        manifest = build_artifacts(
            root, config, [], {"manual": {"status": "ok"}}
        )
        self.assertEqual(manifest["leaderboard"]["ranked_count"], 0)
        self.assertFalse(manifest["leaderboard"]["method_ready"])
        html = (root / "artifacts/site/index.html").read_text(encoding="utf-8")
        self.assertIn("KSR leaderboard", html)
        self.assertIn("∴", html)
        self.assertNotIn("K∴", html)
        self.assertEqual(html.count("aihot.virxact.com"), 1)
        self.assertIn("Ranking method adapted from", html)
        self.assertNotIn("Method notes", html)
        self.assertNotIn("Native modality · Direct model", html)
        self.assertIn("Agent scores and coding do not measure", html)
        self.assertIn("Knowledge", html)
        self.assertIn("Science", html)
        self.assertIn("Reasoning", html)
        self.assertIn("KSR leaderboard launched", html)
        self.assertIn("id=\"view-more\"", html)
        self.assertIn("{% if loop.index > 20 %} hidden{% endif %}", Path("src/ksr_index/templates/index.html.j2").read_text(encoding="utf-8"))
        self.assertIn("readout__ambient", html)
        self.assertNotIn("Current leaders", html)
        self.assertNotIn("Highest reasoning effort", html)
        self.assertNotIn("KSR-ZH", html)
        self.assertNotIn("KSR 总榜", html)
        self.assertTrue((root / "artifacts/site.zip").exists())

    def test_same_matrix_reuses_append_only_snapshot(self):
        root = Path("artifacts/test-idempotent")
        config = load_index_config("config/index.v1.json")
        first = build_artifacts(root, config, [], {})
        second = build_artifacts(root, config, [], {})
        self.assertEqual(first["snapshot_id"], second["snapshot_id"])
        snapshots = list(
            (root / "data/state/snapshots").glob(f"v{config.version}-*")
        )
        self.assertTrue(any(path.name == first["snapshot_id"] for path in snapshots))

    def test_add_score_writes_manual_observation(self):
        import argparse
        from pathlib import Path

        root = Path("artifacts/test-add-score")
        manual = root / "data/manual"
        manual.mkdir(parents=True, exist_ok=True)
        (root / "config").mkdir(parents=True, exist_ok=True)
        (root / "config/index.v1.json").write_bytes(Path("config/index.v1.json").read_bytes())
        args = argparse.Namespace(
            benchmark="hle",
            model="GPT-5.6 Sol (max)",
            score=49.49,
            url="https://artificialanalysis.ai/evaluations/humanitys-last-exam",
            date="2026-08-18",
            effort="max",
            provider="",
            family="",
            modality="text",
            tier="independent",
            notes="fixture",
        )
        added = _add_score(root, args)
        self.assertEqual(added["family_id"], "openai/gpt-5.6-sol")
        self.assertEqual(added["benchmark_id"], "hle")
        text = (root / "data/manual/observations.csv").read_text(encoding="utf-8")
        self.assertIn("49.49", text)
        self.assertIn("openai/gpt-5.6-sol", text)


if __name__ == "__main__":
    unittest.main()
