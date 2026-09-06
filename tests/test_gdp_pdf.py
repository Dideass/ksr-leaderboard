from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ksr_index.adapters.artificial_analysis import ArtificialAnalysisHtmlAdapter
from ksr_index.adapters.base import AdapterError, AliasRegistry, FetchResult
from ksr_index.config import load_index_config
from ksr_index.consensus import select_model_observations
from ksr_index.refresh import _decode_aa_catalog, refresh_source


class GdpPdfTests(unittest.TestCase):
    def setUp(self):
        config = json.loads(Path("config/sources.json").read_text(encoding="utf-8"))
        self.source = next(s for s in config["sources"] if s["id"] == "aa_public_measurements")
        self.source = {**self.source, "score_fields": {"gdp_pdf": {
            **self.source["score_fields"]["gdp_pdf"], "minimum_models": 1
        }}}

    def row(self, effort="max", score=0.332, image=True):
        return {
            "name": f"GPT-6 Astra ({effort})", "slug": f"gpt-6-astra-{effort}",
            "releaseDate": "2026-09-03", "creator": {"slug": "openai"},
            "inputModalityImage": image, "gdpPdfAllPass": score,
            "gdpPdfBreakdown": {"macroCriterionPassRate": 0.81},
            "gdpval": 1584.13,
            "canonicalEvalTokenCounts": {"gdpPdf": {"input": 15037184}},
        }

    def parse(self, rows):
        return ArtificialAnalysisHtmlAdapter(self.source, AliasRegistry([])).parse(FetchResult(
            self.source["id"], json.dumps({"models": rows}).encode(),
            "application/json", "2026-09-05T00:00:00+00:00", 200
        ))

    def test_all_pass_and_native_inputs_survive_effort_selection(self):
        observations = self.parse([self.row(), self.row("high", 0.40, False)])
        self.assertEqual([o.raw_score for o in observations], [0.332, 0.40])
        self.assertEqual([o.modality for o in observations], ["multimodal", "text"])
        self.assertTrue(all(o.is_eligible_native_no_tool() for o in observations))
        self.assertTrue(all(o.sample_size == 500 and o.ci_low is None and o.ci_high is None
                            for o in observations))
        selected = select_model_observations(observations, load_index_config("config/index.v1.json"))
        item = selected["openai/gpt-6-astra"]["gdp_pdf"]
        self.assertAlmostEqual(item.score, 33.2)
        self.assertEqual(item.observation.reasoning_effort, "max")

    def test_only_measured_all_pass_is_imported_and_zero_is_real(self):
        unmeasured = self.row()
        unmeasured["canonicalEvalTokenCounts"] = {}
        absent = self.row()
        absent["gdpPdfAllPass"] = None
        # A criterion score and GDPval score cannot fill a missing All-pass.
        result = self.parse([unmeasured, absent, self.row(score=0)])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].raw_score, 0)

    def test_unknown_input_capability_does_not_get_guessed(self):
        row = self.row()
        del row["inputModalityImage"]
        with self.assertRaisesRegex(AdapterError, "missing image support"):
            self.parse([row])

    def test_deprecated_measurements_survive_but_deleted_rows_do_not(self):
        legacy = {**self.row(), "deprecated": True}
        deleted = {**self.row("high"), "deleted": True}
        observations = self.parse([legacy, deleted])
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].raw_score, 0.332)

    def test_field_coverage_guard_also_applies_to_offline_ingest(self):
        source = {**self.source, "minimum_rows": 1, "score_fields": {
            **self.source["score_fields"], "hle": {
                "field": "hle", "version": "test", "minimum_models": 1,
            },
        }}
        with self.assertRaisesRegex(AdapterError, "too few parsed rows for hle"):
            ArtificialAnalysisHtmlAdapter(source, AliasRegistry([])).validate(
                self.parse([self.row()])
            )

    def test_gdp_pdf_is_synthesis_not_knowledge_entry_evidence(self):
        config = load_index_config("config/index.v1.json")
        groups = {g["id"]: g["benchmarks"] for g in config.settings["entry_groups"]}
        self.assertIn("gdp_pdf", groups["novel_or_synthesis"])
        self.assertNotIn("gdp_pdf", groups["knowledge_or_science"])
        self.assertEqual(config.benchmarks["gdp_pdf"].dimension, "context_reasoning")

    def test_refresh_uses_full_public_catalog_and_fails_closed(self):
        key = bytes(range(32))
        payload = json.dumps({"models": [
            {**self.row(), "deprecated": True}, self.row("high", 0.31, False)
        ]}).encode()
        encrypted = AESGCM(key).encrypt(hashlib.sha256(key).digest()[:12], gzip.compress(payload), None)
        manifest = {"path": "/data/test.txt", "key": key.hex()}
        flight = '1:' + json.dumps({"initialModels": [self.row()], "manifest": manifest})
        page = '<script>self.__next_f.push(' + json.dumps([1, flight]) + ')</script>'
        root = Path("work")
        root.mkdir(parents=True, exist_ok=True)
        snapshot = root / ".tmp_aa_gdp_test.json"
        snapshot.unlink(missing_ok=True)
        self.addCleanup(lambda: snapshot.unlink(missing_ok=True))
        source = {**self.source, "path": snapshot.name}
        with patch("ksr_index.refresh._http_get", side_effect=[
            httpx.Response(200, content=page.encode()), httpx.Response(200, content=encrypted)
        ]) as get:
            result = refresh_source(root, source)
        self.assertEqual(result["gdp_pdf"], 2)
        self.assertEqual(result["merged_from_existing"], 0)
        self.assertEqual(get.call_args_list[1].args[0], "https://artificialanalysis.ai/data/test.txt")
        frozen = snapshot.read_bytes()
        self.assertTrue(json.loads(frozen)[0]["deprecated"])
        self.assertFalse(json.loads(frozen)[0]["deleted"])
        parsed = ArtificialAnalysisHtmlAdapter(source, AliasRegistry([])).parse(FetchResult(
            source["id"], frozen, "application/json", "2026-09-05T00:00:00+00:00", 200
        ))
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0].raw_score, 0.332)
        with patch("ksr_index.refresh._http_get", side_effect=[
            httpx.Response(200, content=page.encode()), httpx.Response(200, content=b"corrupt")
        ]):
            with self.assertRaises(AdapterError):
                refresh_source(root, source)
        self.assertEqual(snapshot.read_bytes(), frozen)
        source["score_fields"]["gdp_pdf"]["minimum_models"] = 3
        with patch("ksr_index.refresh._http_get", side_effect=[
            httpx.Response(200, content=page.encode()), httpx.Response(200, content=encrypted)
        ]):
            with self.assertRaisesRegex(AdapterError, "too few measured rows"):
                refresh_source(root, source)
        self.assertEqual(snapshot.read_bytes(), frozen)

    def test_bad_catalog_key_or_payload_is_rejected(self):
        with self.assertRaises(AdapterError):
            _decode_aa_catalog(b"broken", "00" * 32)


if __name__ == "__main__":
    unittest.main()
