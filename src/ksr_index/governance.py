from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Iterable

import numpy as np

from .models import BenchmarkSpec


def benchmark_governance_report(
    specs: Iterable[BenchmarkSpec],
    scores_by_benchmark: dict[str, list[float]],
) -> list[dict[str, object]]:
    report: list[dict[str, object]] = []
    for spec in specs:
        values = sorted(scores_by_benchmark.get(spec.id, []), reverse=True)
        top = values[:10]
        top_median = median(top) if top else None
        iqr = (
            float(np.percentile(top, 75) - np.percentile(top, 25))
            if len(top) >= 4
            else None
        )
        saturated_signal = bool(
            top_median is not None
            and iqr is not None
            and (top_median > 90.0 or iqr < 2.5)
        )
        report.append(
            {
                "benchmark_id": spec.id,
                "title": spec.title,
                "status": spec.status,
                "model_count": len(values),
                "top10_median": top_median,
                "top10_iqr": iqr,
                "saturation_review_signal": saturated_signal,
                "notes": spec.notes,
            }
        )
    return report


def platform_weight_report(specs: Iterable[BenchmarkSpec], index_id: str) -> dict[str, float]:
    weights: dict[str, float] = defaultdict(float)
    for spec in specs:
        weights[spec.source_platform] += spec.weights[index_id]
    return dict(sorted(weights.items()))

