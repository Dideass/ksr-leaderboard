from __future__ import annotations

import unittest

from ksr_index.consensus import _clean_display_name
from ksr_index.identity import public_model_identity


class PublicIdentityTests(unittest.TestCase):
    def family(self, name: str, slug: str, date: str) -> tuple[str, str]:
        result = public_model_identity(
            name=name, slug=slug, provider="", release_date=date
        )
        return str(result["family_id"]), str(result["reasoning_effort"])

    def test_reasoning_modes_and_compact_endpoint_dates_merge(self):
        self.assertEqual(
            self.family(
                "DeepSeek V4 Pro (Reasoning, Max Effort)",
                "deepseek-v4-pro-0424",
                "2026-04-24",
            ),
            ("deepseek/deepseek-v4-pro", "max"),
        )
        self.assertEqual(
            self.family(
                "DeepSeek V4 Pro (Non-reasoning)",
                "deepseek-v4-pro-0424-non-reasoning",
                "2026-04-24",
            ),
            ("deepseek/deepseek-v4-pro", "none"),
        )
        self.assertEqual(
            self.family(
                "DeepSeek V4 Flash (Reasoning, Max Effort)",
                "deepseek-v4-flash-0420",
                "2026-04-24",
            )[0],
            "deepseek/deepseek-v4-flash",
        )

    def test_adaptive_is_configuration_but_preview_is_product_variant(self):
        self.assertEqual(
            self.family(
                "Claude Sonnet 4.6 (Adaptive Reasoning, Max Effort)",
                "claude-sonnet-4-6-adaptive",
                "2026-02-17",
            )[0],
            "anthropic/claude-sonnet-4.6",
        )
        self.assertEqual(
            self.family("Gemini 3 Pro Preview", "gemini-3-pro", "2025-11-18")[0],
            "google/gemini-3-pro-preview",
        )

    def test_experimental_remains_distinct_from_final(self):
        experimental, _ = self.family(
            "DeepSeek V3.2 Exp (Reasoning)",
            "deepseek-v3-2-reasoning-0925",
            "2025-09-25",
        )
        final, _ = self.family(
            "DeepSeek V3.2 (Reasoning)", "deepseek-v3-2-reasoning", "2025-12-01"
        )
        self.assertEqual(experimental, "deepseek/deepseek-v3.2-experimental")
        self.assertEqual(final, "deepseek/deepseek-v3.2")
        self.assertNotEqual(experimental, final)

    def test_livebench_compact_effort_suffixes(self):
        self.assertEqual(
            self.family("gpt-5.6-sol-max", "gpt-5.6-sol-max", "2026-07-09"),
            ("openai/gpt-5.6-sol", "max"),
        )
        self.assertEqual(
            self.family(
                "claude-opus-5-max-effort",
                "claude-opus-5-max-effort",
                "2026-07-24",
            ),
            ("anthropic/claude-opus-5", "max"),
        )
        self.assertEqual(
            self.family(
                "gemini-3.7-flash-high",
                "gemini-3.7-flash-high",
                "2026-08-13",
            ),
            ("google/gemini-3.7-flash", "high"),
        )

    def test_fallback_suffix_is_configuration_not_a_new_family(self):
        self.assertEqual(
            self.family(
                "Claude Fable 5 (Max Effort, Opus 4.8 Fallback)",
                "claude-fable-5-fallback",
                "2026-06-09",
            ),
            ("anthropic/claude-fable-5", "max"),
        )

    def test_qwen_max_is_a_product_not_an_effort_setting(self):
        self.assertEqual(
            self.family("Qwen3.8 Max", "qwen3-8-max", "2026-08-03"),
            ("alibaba/qwen3.8-max", "default"),
        )
        self.assertEqual(
            self.family("qwen3.7-max", "qwen3.7-max", "2026-05-19"),
            ("alibaba/qwen3.7-max", "default"),
        )
        self.assertEqual(_clean_display_name("Qwen3.8 Max"), "Qwen3.8 Max")
        self.assertEqual(_clean_display_name("Qwen3.7 Max"), "Qwen3.7 Max")
        self.assertEqual(_clean_display_name("GPT-5.6 Sol max"), "GPT-5.6 Sol")


if __name__ == "__main__":
    unittest.main()
