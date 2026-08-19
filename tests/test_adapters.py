from __future__ import annotations

import json
import io
import unittest
from unittest.mock import patch

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from ksr_index.adapters.base import AdapterError, AliasRegistry, FetchResult
from ksr_index.adapters.artificial_analysis import ArtificialAnalysisHtmlAdapter
from ksr_index.adapters.curated_csv import CuratedLeaderboardCsvAdapter
from ksr_index.adapters.kaggle import KaggleLeaderboardAdapter
from ksr_index.adapters.manual import ManualCsvAdapter
from ksr_index.adapters.matharena import MathArenaParquetAdapter
from ksr_index.adapters.arc_prize import ArcPrizeLeaderboardAdapter
from ksr_index.adapters.vals import ValsHtmlAdapter
from ksr_index.adapters.wide_csv import CategoryMeanCsvAdapter, WideCsvAdapter


class AdapterTests(unittest.TestCase):
    def test_artificial_analysis_public_payload_imports_measured_fields(self):
        source = {
            "id": "aa-public-test",
            "adapter": "artificial_analysis_html",
            "minimum_rows": 2,
            "source_tier": "independent",
            "public_url": "https://example.test/aa",
            "score_fields": {
                "critpt": {
                    "field": "critpt", "token_key": "critpt", "version": "aa-v1",
                    "metric": "pass_rate", "sample_size": 350,
                },
                "aa_omniscience": {
                    "field": "omniscience", "token_key": "omniscience", "version": "aa-v1",
                    "metric": "signed_index", "scale": 1,
                },
            },
        }
        adapter = ArtificialAnalysisHtmlAdapter(source, AliasRegistry([]))
        data = [{
            "name": "GPT-5.6 Sol (xhigh)", "slug": "gpt-5-6-sol-xhigh",
            "release_date": "2026-07-09", "deleted": False,
            "model_creators": {"slug": "openai"},
            "critpt": 0.30, "omniscience": 21.5,
            "canonical_eval_token_counts": {"critpt": {"input": 1}, "omniscience": {"input": 1}},
        }, {
            "name": "Claude Fable 5 (Max Effort, Opus 4.8 Fallback)",
            "slug": "claude-fable-5-fallback", "release_date": "2026-07-24",
            "deleted": False, "model_creators": {"slug": "anthropic"},
            "critpt": 0.99, "omniscience": 99,
            "canonical_eval_token_counts": {"critpt": {"input": 1}, "omniscience": {"input": 1}},
        }]
        flight = '1:["$","div",null,{"defaultData":' + json.dumps(data) + '}]'
        script = "<script>self.__next_f.push(" + json.dumps([1, flight]) + ")</script>"
        fetched = FetchResult("aa-public-test", script.encode(), "text/html", "2026-08-18T00:00:00+00:00", 200)
        observations = adapter.parse(fetched)
        adapter.validate(observations)
        self.assertEqual(len(observations), 4)
        by_family = {item.family_id for item in observations}
        self.assertEqual(by_family, {"openai/gpt-5.6-sol", "anthropic/claude-fable-5"})
        sol = next(item for item in observations if item.family_id == "openai/gpt-5.6-sol")
        fable = next(item for item in observations if item.family_id == "anthropic/claude-fable-5")
        self.assertEqual(sol.reasoning_effort, "xhigh")
        self.assertEqual(sol.raw_score, 0.30)
        self.assertIn("fallback", fable.notes.lower())
        self.assertEqual(fable.raw_score, 0.99)

    def test_artificial_analysis_initial_models_camelcase_payload(self):
        source = {
            "id": "aa-public-test",
            "adapter": "artificial_analysis_html",
            "minimum_rows": 1,
            "source_tier": "independent",
            "public_url": "https://example.test/aa",
            "score_fields": {
                "hle": {
                    "field": "hle", "token_key": "hle", "version": "aa-v1",
                    "metric": "canonical", "sample_size": 2158,
                },
                "critpt": {
                    "field": "critpt", "token_key": "critpt", "version": "aa-v1",
                    "metric": "pass_rate", "sample_size": 350,
                },
            },
        }
        adapter = ArtificialAnalysisHtmlAdapter(source, AliasRegistry([]))
        data = [{
            "name": "GLM-5.3 (max)", "slug": "glm-5-3", "shortName": "GLM-5.3 (max)",
            "releaseDate": "2026-08-18", "deprecated": False,
            "creator": {"slug": "zai", "name": "Z AI"},
            "hle": 0.4226, "critpt": 0.1914,
            "canonicalEvalTokenCounts": {"hle": {"input": 1}, "critpt": {"input": 1}},
        }]
        flight = '1:["$","div",null,{"slug":"omniscience","initialModels":' + json.dumps(data) + "}]"
        script = "<script>self.__next_f.push(" + json.dumps([1, flight]) + ")</script>"
        fetched = FetchResult("aa-public-test", script.encode(), "text/html", "2026-08-19T00:00:00+00:00", 200)
        observations = adapter.parse(fetched)
        adapter.validate(observations)
        self.assertEqual({item.family_id for item in observations}, {"zhipu/glm-5.3"})
        by_bench = {item.benchmark_id: item for item in observations}
        self.assertAlmostEqual(by_bench["hle"].raw_score, 0.4226)
        self.assertEqual(by_bench["hle"].reasoning_effort, "max")

    def test_artificial_analysis_json_snapshot_imports_hle(self):
        source = {
            "id": "aa-json-test",
            "adapter": "artificial_analysis_html",
            "minimum_rows": 1,
            "source_tier": "independent",
            "public_url": "https://example.test/aa",
            "score_fields": {
                "hle": {
                    "field": "hle", "token_key": "hle", "version": "aa-hle",
                    "metric": "canonical", "sample_size": 2158,
                    "source_url": "https://example.test/hle",
                },
                "gpqa_diamond": {
                    "field": "gpqa", "token_key": "gpqa",
                    "version": "aa-gpqa", "metric": "multiple_choice",
                    "source_url": "https://example.test/gpqa",
                },
            },
        }
        adapter = ArtificialAnalysisHtmlAdapter(source, AliasRegistry([]))
        payload = [{
            "name": "GPT-5.6 Sol (max)", "slug": "gpt-5-6-sol",
            "release_date": "2026-07-09", "deleted": False,
            "model_creators": {"slug": "openai"},
            "hle": 0.4949, "gpqa": 0.884,
            "canonical_eval_token_counts": {"hle": {"input": 1}, "gpqa": {"input": 1}},
        }]
        fetched = FetchResult(
            "aa-json-test",
            json.dumps(payload).encode(),
            "application/json",
            "2026-08-18T00:00:00+00:00",
            200,
        )
        observations = adapter.parse(fetched)
        adapter.validate(observations)
        by_bench = {item.benchmark_id: item for item in observations}
        self.assertEqual(set(by_bench), {"hle", "gpqa_diamond"})
        self.assertEqual(by_bench["hle"].family_id, "openai/gpt-5.6-sol")
        self.assertAlmostEqual(by_bench["hle"].raw_score, 0.4949)
        self.assertAlmostEqual(by_bench["gpqa_diamond"].raw_score, 0.884)
        self.assertEqual(
            by_bench["hle"].source_url,
            "https://example.test/hle",
        )

    def test_vals_json_snapshot_imports_mmlu_pro(self):
        source = {
            "id": "vals-mmlu-test",
            "adapter": "vals_html",
            "minimum_rows": 1,
            "source_tier": "independent",
            "public_url": "https://www.vals.ai/benchmarks/mmlu_pro",
            "benchmark_id": "mmlu_pro",
            "benchmark_version": "vals-test",
            "protocol_hash": "vals-mmlu-pro-test",
            "sample_size": 12032,
            "tool_mode": "none",
            "modality": "text",
        }
        adapter = ValsHtmlAdapter(source, AliasRegistry([]))
        payload = {
            "updated": "2026-08-15",
            "benchmark": "mmlu_pro",
            "models": [
                {
                    "id": "openai/gpt-5.6-sol",
                    "provider": "OpenAI",
                    "accuracy": 89.1,
                    "stderr": 0.308,
                    "reasoning_effort": "max",
                    "compute_effort": None,
                },
                {
                    "id": "anthropic/claude-fable-5",
                    "provider": "Anthropic",
                    "accuracy": 91.502,
                    "stderr": 0.278,
                    "reasoning_effort": None,
                    "compute_effort": "max",
                },
            ],
        }
        fetched = FetchResult(
            "vals-mmlu-test",
            json.dumps(payload).encode(),
            "application/json",
            "2026-08-18T00:00:00+00:00",
            200,
        )
        observations = adapter.parse(fetched)
        adapter.validate(observations)
        by_family = {item.family_id: item for item in observations}
        self.assertEqual(set(by_family), {"openai/gpt-5.6-sol", "anthropic/claude-fable-5"})
        sol = by_family["openai/gpt-5.6-sol"]
        fable = by_family["anthropic/claude-fable-5"]
        self.assertEqual(sol.benchmark_id, "mmlu_pro")
        self.assertAlmostEqual(sol.raw_score, 89.1)
        self.assertEqual(sol.reasoning_effort, "max")
        self.assertEqual(fable.reasoning_effort, "max")
        self.assertTrue(sol.is_eligible_native_no_tool())
        self.assertAlmostEqual(sol.ci_low, 89.1 - 1.96 * 0.308, places=5)

    def test_arc_prize_json_imports_verified_cot_only(self):
        source = {
            "id": "arc-test",
            "adapter": "arc_prize_json",
            "minimum_rows": 2,
            "source_tier": "benchmark_host",
            "public_url": "https://arcprize.org/leaderboard",
            "benchmark_id": "arc_agi_2",
            "benchmark_version": "official-semi-private-120",
            "protocol_hash": "arc-test",
            "tool_mode": "none",
            "modality": "grid-visual",
        }
        adapter = ArcPrizeLeaderboardAdapter(source, AliasRegistry([]))
        payload = {
            "generated_at": "2026-08-13T23:42:30.422Z",
            "dataset": "v2_Semi_Private",
            "rows": [
                {
                    "modelId": "gpt-5-4-xhigh",
                    "displayName": "GPT-5.4 (XHigh)",
                    "provider": "OpenAI",
                    "score": 0.74,
                    "modelReleaseDate": "2026-03-04T00:00:00.000Z",
                    "resultsUrl": "",
                },
                {
                    "modelId": "deepseek-v4-flash-0731-max",
                    "displayName": "DeepSeek V4 Flash 0731 (Max)",
                    "provider": "DeepSeek",
                    "score": 0.614,
                    "modelReleaseDate": "2026-07-31T00:00:00.000Z",
                    "resultsUrl": "/results/deepseek-v4-flash-0731",
                },
            ],
        }
        fetched = FetchResult(
            "arc-test",
            json.dumps(payload).encode(),
            "application/json",
            "2026-08-18T00:00:00+00:00",
            200,
        )
        observations = adapter.parse(fetched)
        adapter.validate(observations)
        by_family = {item.family_id: item for item in observations}
        self.assertEqual(set(by_family), {"openai/gpt-5.4", "deepseek/deepseek-v4-flash"})
        gpt = by_family["openai/gpt-5.4"]
        deepseek = by_family["deepseek/deepseek-v4-flash"]
        self.assertAlmostEqual(gpt.raw_score, 74.0)
        self.assertEqual(gpt.reasoning_effort, "xhigh")
        self.assertTrue(gpt.is_eligible_native_no_tool())
        self.assertEqual(deepseek.reasoning_effort, "max")
        self.assertEqual(
            deepseek.source_url, "https://arcprize.org/results/deepseek-v4-flash-0731"
        )

    def test_native_multimodal_no_tool_is_eligible(self):
        from tests.helpers import observation

        item = observation("bench-a", 50, model_id="model-a")
        item.modality = "multimodal"
        self.assertTrue(item.is_eligible_native_no_tool())
        self.assertFalse(item.is_eligible_text_no_tool())

    def test_curated_csv_can_infer_public_multimodal_identity(self):
        adapter = CuratedLeaderboardCsvAdapter(
            {
                "id": "hle-standard", "adapter": "curated_csv", "path": "unused.csv",
                "infer_public_identity": True, "protocol_hash": "hle-standard-v1",
            },
            AliasRegistry([]),
        )
        content = (
            "benchmark_id,benchmark_version,model_display,score_pct,ci_half_width_pct,"
            "reasoning_effort,tool_mode,modality,source_url,as_of\n"
            "hle,finalized-2500,GPT-5.4 (xhigh),44.3,1.9,xhigh,none,multimodal,"
            "https://example.test/hle,2026-08-18\n"
        ).encode()
        item = adapter.parse(FetchResult("hle-standard", content, "text/csv", "2026-08-18T00:00:00+00:00", 200))[0]
        self.assertEqual(item.family_id, "openai/gpt-5.4")
        self.assertEqual(item.reasoning_effort, "xhigh")
        self.assertTrue(item.is_eligible_native_no_tool())

    def test_matharena_first_answer_problem_equal_aggregate(self):
        table = pa.table({
            "problem_idx": [0, 0, 0, 1, 1, 2],
            "model_name": ["Model A"] * 6,
            "model_config": ["default"] * 6,
            "idx_answer": [0, 1, 0, 0, 0, 0],
            "correct": [True, True, False, True, False, True],
        })
        buffer = io.BytesIO()
        pq.write_table(table, buffer)
        source = {
            "id": "matharena-test",
            "adapter": "matharena_parquet",
            "public_url": "https://example.test/matharena",
            "benchmark_id": "matharena_test",
            "benchmark_version": "rev-test",
            "protocol_hash": "matharena-test-v1",
            "minimum_rows": 1,
        }
        aliases = AliasRegistry([{
            "source_id": "matharena-test", "source_model_name": "Model A",
            "provider": "Lab", "model_id": "model-a", "family_id": "model-a",
            "display_name": "Model A", "endpoint_date": "2026-08-01",
            "reasoning_effort": "default", "protocol_compatible": "true",
        }])
        adapter = MathArenaParquetAdapter(source, aliases)
        result = FetchResult("matharena-test", buffer.getvalue(), "application/parquet", "2026-08-17T00:00:00+00:00", 200)
        observations = adapter.parse(result)
        adapter.validate(observations)
        self.assertEqual(len(observations), 1)
        # idx_answer=0 leaves problem scores [0, 1, 1], equal problem weight.
        self.assertAlmostEqual(observations[0].raw_score, 2 / 3)
        self.assertIn("default", observations[0].model_id)

    def test_multinrc_paper_csv_imports_as_frozen_observations(self):
        source = {
            "id": "multinrc_chinese_paper",
            "adapter": "manual_csv",
            "path": "data/manual/multinrc_chinese.csv",
            "minimum_rows": 14,
        }
        adapter = ManualCsvAdapter(source, AliasRegistry([]))
        fetched = adapter.fetch()
        observations = adapter.parse(fetched)
        adapter.validate(observations)
        self.assertEqual(len(observations), 14)
        self.assertTrue(all(item.benchmark_version == "paper-v1-table4-zh-derived" for item in observations))
        self.assertTrue(all(item.protocol_hash and item.raw_hash for item in observations))

    def test_kaggle_fixture_uses_alias_registry(self):
        source = {
            "id": "kaggle-test",
            "adapter": "kaggle_json",
            "url": "https://example.test/api",
            "public_url": "https://example.test/board",
            "benchmark_id": "simpleqa_verified_f1",
            "benchmark_version": "v1",
            "model_path": "model.name",
            "score_path": "score",
            "metric": "f1",
            "protocol_hash": "fixture",
            "minimum_rows": 1,
        }
        aliases = AliasRegistry(
            [
                {
                    "source_id": "kaggle-test",
                    "source_model_name": "Model X High",
                    "provider": "Lab X",
                    "model_id": "model-x-2026-01-01",
                    "family_id": "Model X",
                    "display_name": "Model X (high)",
                    "endpoint_date": "2026-01-01",
                    "reasoning_effort": "high",
                    "protocol_compatible": "true",
                }
            ]
        )
        adapter = KaggleLeaderboardAdapter(source, aliases)
        payload = {"leaderboard": [{"model": {"name": "Model X High"}, "score": 61.5}]}
        fetched = FetchResult(
            source_id="kaggle-test",
            content=json.dumps(payload).encode(),
            content_type="application/json",
            retrieved_at="2026-08-17T00:00:00+00:00",
            status_code=200,
        )
        observations = adapter.parse(fetched)
        adapter.validate(observations)
        self.assertEqual(observations[0].provider, "Lab X")
        self.assertEqual(observations[0].reasoning_effort, "high")
        self.assertTrue(observations[0].protocol_compatible)

    def test_unmapped_network_model_is_not_scoring_eligible(self):
        source = {
            "id": "kaggle-test",
            "adapter": "kaggle_json",
            "url": "https://example.test/api",
            "benchmark_id": "simpleqa_verified_f1",
            "benchmark_version": "v1",
            "model_path": "model.name",
            "score_path": "score",
            "protocol_hash": "fixture",
        }
        adapter = KaggleLeaderboardAdapter(source, AliasRegistry([]))
        fetched = FetchResult(
            source_id="kaggle-test",
            content=b'{"rows":[{"model":{"name":"Mystery"},"score":55}]}',
            content_type="application/json",
            retrieved_at="2026-08-17T00:00:00+00:00",
            status_code=200,
        )
        item = adapter.parse(fetched)[0]
        self.assertFalse(item.protocol_compatible)
        self.assertEqual(item.reasoning_effort, "unknown")

    def test_kaggle_benchmarks_api_nested_task_result(self):
        source = {
            "id": "kaggle-test",
            "adapter": "kaggle_json",
            "url": "https://example.test/api",
            "benchmark_id": "simpleqa_verified_f1",
            "benchmark_version": "auto",
            "task_name": "simpleqa_verified_task",
            "metric": "f1",
            "protocol_hash": "simpleqa",
        }
        payload = {
            "rows": [
                {
                    "modelVersionName": "Model Y",
                    "modelVersionSlug": "model-y-20260801",
                    "taskResults": [
                        {
                            "benchmarkTaskName": "simpleqa_verified_task",
                            "taskVersion": 7,
                            "result": {
                                "numericResult": {
                                    "value": 0.775,
                                    "confidenceInterval": 0.025,
                                    "hasConfidenceInterval": True,
                                },
                                "evaluationDate": "2026-03-10T00:00:00Z",
                            },
                        }
                    ],
                }
            ]
        }
        adapter = KaggleLeaderboardAdapter(source, AliasRegistry([]))
        fetched = FetchResult(
            source_id="kaggle-test",
            content=json.dumps(payload).encode(),
            content_type="application/json",
            retrieved_at="2026-08-17T00:00:00+00:00",
            status_code=200,
        )
        item = adapter.parse(fetched)[0]
        self.assertEqual(item.benchmark_version, "v7")
        self.assertEqual(item.eval_date, "2026-03-10")
        self.assertAlmostEqual(item.raw_score, 0.775)
        self.assertAlmostEqual(item.ci_low, 0.75)
        self.assertAlmostEqual(item.ci_high, 0.8)
        self.assertEqual(item.protocol_hash, "simpleqa-v7")

    def test_kaggle_benchmark_can_quarantine_known_zero_row(self):
        source = {
            "id": "multiloko-test",
            "adapter": "kaggle_json",
            "url": "https://example.test/api",
            "benchmark_id": "multiloko_zh",
            "benchmark_version": "v1",
            "task_name": "EM Simplified Mandarin",
            "protocol_hash": "multiloko",
            "exclude_model_names": ["Bad Model"],
        }
        payload = {"rows": [
            {"modelVersionName": "Bad Model", "modelVersionSlug": "bad-model", "taskResults": [
                {"benchmarkTaskName": "EM Simplified Mandarin", "taskVersion": 1,
                 "result": {"numericResult": {"value": 0}}}
            ]},
            {"modelVersionName": "Good Model", "modelVersionSlug": "good-model", "taskResults": [
                {"benchmarkTaskName": "EM Simplified Mandarin", "taskVersion": 1,
                 "result": {"numericResult": {"value": 0.5}}}
            ]},
        ]}
        adapter = KaggleLeaderboardAdapter(source, AliasRegistry([]))
        fetched = FetchResult("multiloko-test", json.dumps(payload).encode(), "application/json", "2026-08-17T00:00:00+00:00", 200)
        observations = adapter.parse(fetched)
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].source_model_name, "Good Model")

    def test_empty_or_schema_drift_payload_is_rejected(self):
        source = {
            "id": "kaggle-test",
            "adapter": "kaggle_json",
            "url": "https://example.test/api",
            "benchmark_id": "simpleqa_verified_f1",
            "benchmark_version": "v1",
            "score_path": "score",
        }
        adapter = KaggleLeaderboardAdapter(source, AliasRegistry([]))
        for payload in ({}, {"rows": [{"unexpected": 1}]}):
            fetched = FetchResult(
                source_id="kaggle-test",
                content=json.dumps(payload).encode(),
                content_type="application/json",
                retrieved_at="2026-08-17T00:00:00+00:00",
                status_code=200,
            )
            with self.assertRaises(AdapterError):
                adapter.parse(fetched)

    def test_duplicate_rows_are_rejected(self):
        source = {
            "id": "kaggle-test",
            "adapter": "kaggle_json",
            "url": "https://example.test/api",
            "benchmark_id": "simpleqa_verified_f1",
            "benchmark_version": "v1",
            "score_path": "score",
        }
        adapter = KaggleLeaderboardAdapter(source, AliasRegistry([]))
        payload = {"rows": [{"modelName": "Same", "score": 1}] * 2}
        fetched = FetchResult(
            source_id="kaggle-test",
            content=json.dumps(payload).encode(),
            content_type="application/json",
            retrieved_at="2026-08-17T00:00:00+00:00",
            status_code=200,
        )
        with self.assertRaises(AdapterError):
            adapter.validate(adapter.parse(fetched))

    def test_http_429_is_wrapped_as_adapter_error(self):
        source = {
            "id": "kaggle-test",
            "adapter": "kaggle_json",
            "url": "https://example.test/api",
            "benchmark_id": "simpleqa_verified_f1",
            "benchmark_version": "v1",
        }
        adapter = KaggleLeaderboardAdapter(source, AliasRegistry([]))
        response = httpx.Response(
            429,
            request=httpx.Request("GET", "https://example.test/api"),
        )
        with patch("httpx.Client.get", return_value=response):
            with self.assertRaises(AdapterError):
                adapter.fetch()

    def test_mutable_latest_alias_becomes_dated_snapshot(self):
        source = {
            "id": "kaggle-test",
            "adapter": "kaggle_json",
            "url": "https://example.test/api",
            "benchmark_id": "simpleqa_verified_f1",
            "benchmark_version": "v1",
            "score_path": "score",
            "protocol_hash": "fixture",
        }
        aliases = AliasRegistry(
            [{
                "source_id": "kaggle-test",
                "source_model_name": "Model Latest",
                "provider": "Lab",
                "model_id": "model-latest",
                "family_id": "Model Latest",
                "display_name": "Model Latest",
                "endpoint_date": "",
                "reasoning_effort": "default",
                "protocol_compatible": "true",
                "mutable_alias": "true",
            }]
        )
        adapter = KaggleLeaderboardAdapter(source, aliases)
        fetched = FetchResult(
            source_id="kaggle-test",
            content=b'{"rows":[{"modelName":"Model Latest","score":50}]}',
            content_type="application/json",
            retrieved_at="2026-08-17T00:00:00+00:00",
            status_code=200,
        )
        item = adapter.parse(fetched)[0]
        self.assertEqual(item.endpoint_date, "2026-08-17")
        self.assertEqual(item.model_id, "model-latest@2026-08-17")
        self.assertTrue(item.is_eligible_text_no_tool())

    def test_livebench_hf_and_epoch_csv_fixtures(self):
        fixtures = [
            ("livebench-fixture", {"livebench_reasoning": "reasoning", "livebench_math": "math"}, "model,reasoning,math\nModel A,42,51\n", 2),
            ("huggingface-fixture", {"matharena": "score"}, "model,score\nModel A,38\n", 1),
            ("epoch-fixture", {"gpqa_diamond": "score"}, "model,score\nModel A,73\n", 1),
        ]
        for source_id, columns, content, expected in fixtures:
            with self.subTest(source=source_id):
                source = {
                    "id": source_id,
                    "adapter": "wide_csv",
                    "url": "https://example.test/data.csv",
                    "benchmark_version": "release-2026-08",
                    "model_column": "model",
                    "score_columns": columns,
                    "protocol_hash": f"{source_id}-release-2026-08",
                }
                aliases = AliasRegistry([{
                    "source_id": source_id,
                    "source_model_name": "Model A",
                    "provider": "Lab",
                    "model_id": "model-a-2026-08-01",
                    "family_id": "Model A",
                    "display_name": "Model A",
                    "endpoint_date": "2026-08-01",
                    "reasoning_effort": "default",
                    "protocol_compatible": "true",
                }])
                adapter = WideCsvAdapter(source, aliases)
                fetched = FetchResult(
                    source_id=source_id,
                    content=content.encode(),
                    content_type="text/csv",
                    retrieved_at="2026-08-17T00:00:00+00:00",
                    status_code=200,
                )
                observations = adapter.parse(fetched)
                adapter.validate(observations)
                self.assertEqual(len(observations), expected)
                self.assertTrue(all(item.is_eligible_text_no_tool() for item in observations))

    def test_livebench_category_mean_excludes_unselected_columns(self):
        source = {
            "id": "livebench-release",
            "adapter": "category_mean_csv",
            "url": "https://example.test/table.csv",
            "benchmark_version": "2026-06-25",
            "model_column": "model",
            "category_columns": {
                "livebench_reasoning": ["logic", "spatial"],
                "livebench_math": ["amps", "olympiad"],
            },
            "eval_date": "2026-06-25",
            "protocol_hash": "livebench-2026-06-25",
        }
        aliases = AliasRegistry([{
            "source_id": "livebench-release",
            "source_model_name": "model-a-high",
            "provider": "Lab",
            "model_id": "model-a-high",
            "family_id": "model-a",
            "display_name": "Model A high",
            "endpoint_date": "2026-06-25",
            "reasoning_effort": "high",
            "protocol_compatible": "true",
        }])
        adapter = CategoryMeanCsvAdapter(source, aliases)
        fetched = FetchResult(
            source_id="livebench-release",
            content=b"model,logic,spatial,amps,olympiad,coding,agentic\nmodel-a-high,40,60,70,90,100,100\n",
            content_type="text/csv",
            retrieved_at="2026-08-17T00:00:00+00:00",
            status_code=200,
        )
        observations = adapter.parse(fetched)
        self.assertEqual([item.raw_score for item in observations], [50.0, 80.0])
        self.assertEqual(
            {item.benchmark_id for item in observations},
            {"livebench_reasoning", "livebench_math"},
        )

    def test_livebench_infers_identity_when_alias_is_missing(self):
        source = {
            "id": "livebench-release",
            "adapter": "category_mean_csv",
            "benchmark_version": "2026-06-25",
            "model_column": "model",
            "infer_public_identity": True,
            "eval_date": "2026-07-09",
            "public_url": "https://livebench.ai/",
            "category_columns": {
                "livebench_reasoning": ["logic", "spatial"],
            },
            "protocol_hash": "livebench-test",
        }
        adapter = CategoryMeanCsvAdapter(source, AliasRegistry([]))
        fetched = FetchResult(
            "livebench-release",
            b"model,logic,spatial\ngpt-5.6-sol-max,90,94\n",
            "text/csv",
            "2026-08-18T00:00:00+00:00",
            200,
        )
        item = adapter.parse(fetched)[0]
        self.assertEqual(item.family_id, "openai/gpt-5.6-sol")
        self.assertEqual(item.reasoning_effort, "max")
        self.assertTrue(item.is_eligible_native_no_tool())

    def test_curated_csv_preserves_unknown_protocol_and_uses_alias_identity(self):
        source = {
            "id": "curated-test",
            "adapter": "curated_csv",
            "path": "unused.csv",
            "protocol_hash": "curated-v1",
            "source_tier": "benchmark_author",
        }
        adapter = CuratedLeaderboardCsvAdapter(source, AliasRegistry([{
            "source_id": "*",
            "source_model_name": "GPT-5",
            "provider": "openai",
            "model_id": "gpt-5-2025-08-07",
            "family_id": "openai/gpt-5",
            "endpoint_date": "2025-08-07",
            "reasoning_effort": "default",
            "protocol_compatible": "true",
        }]))
        fetched = FetchResult(
            "curated-test",
            b"benchmark_id,version,split,model_display,score_pct,ci_half_width_pct,reasoning_effort,tool_mode,modality,protocol_note,source_url,as_of\ncritpt,v1,public,GPT-5,5.7,,unknown,not_reported,text,protocol unavailable,https://example.test/critpt,2026-08-17\n",
            "text/csv", "2026-08-17T00:00:00+00:00", 200,
        )
        item = adapter.parse(fetched)[0]
        self.assertEqual(item.provider, "openai")
        self.assertEqual(item.endpoint_date, "2025-08-07")
        self.assertEqual(item.reasoning_effort, "unknown")
        self.assertEqual(item.tool_mode, "not_reported")
        self.assertFalse(item.is_eligible_text_no_tool())

    def test_curated_alias_maps_explicit_hle_endpoint_but_keeps_row_effort(self):
        adapter = CuratedLeaderboardCsvAdapter(
            {"id": "frontier_audit_hle_text", "adapter": "curated_csv", "path": "unused.csv", "protocol_hash": "hle"},
            AliasRegistry.from_csv("data/manual/model_aliases.csv"),
        )
        fetched = FetchResult(
            "frontier_audit_hle_text",
            b"benchmark_id,version,split,model_display,score_pct,ci_half_width_pct,reasoning_effort,tool_mode,modality,protocol_note,source_url,as_of\n"
            b"hle_text,v1,text,gpt-5.4-2026-03-05,36.47,,xhigh,none,text,,https://example.test/hle,2026-08-17\n",
            "text/csv", "2026-08-17T00:00:00+00:00", 200,
        )
        item = adapter.parse(fetched)[0]
        self.assertEqual(item.endpoint_date, "2026-03-05")
        self.assertEqual(item.reasoning_effort, "xhigh")
        self.assertTrue(item.is_eligible_text_no_tool())


if __name__ == "__main__":
    unittest.main()
