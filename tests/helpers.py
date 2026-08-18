from __future__ import annotations

from ksr_index.models import Observation


def observation(
    benchmark_id: str,
    score: float,
    *,
    model_id: str = "model-1-2026-01-01",
    family_id: str = "Model 1",
    provider: str = "Lab",
    effort: str = "high",
    endpoint_date: str = "2026-01-01",
    source_tier: str = "benchmark_host",
    source_id: str = "fixture",
) -> Observation:
    return Observation(
        benchmark_id=benchmark_id,
        benchmark_version="v1",
        model_id=model_id,
        family_id=family_id,
        provider=provider,
        display_name=family_id,
        endpoint_date=endpoint_date,
        reasoning_effort=effort,
        raw_score=score,
        metric="canonical",
        source_id=source_id,
        source_url="https://example.test/benchmark",
        source_tier=source_tier,
        eval_date="2026-02-01",
        protocol_hash="fixture-v1",
        raw_hash=f"{benchmark_id}-{model_id}-{source_id}",
    )

