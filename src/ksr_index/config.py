from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import BenchmarkSpec


@dataclass(slots=True)
class IndexConfig:
    version: str
    benchmarks: dict[str, BenchmarkSpec]
    dimensions: dict[str, str]
    settings: dict[str, Any]

    def active(self) -> list[BenchmarkSpec]:
        return [
            spec
            for spec in self.benchmarks.values()
            if spec.status == "active" and spec.weight_index > 0
        ]

    def validate(self) -> list[str]:
        warnings: list[str] = []
        total = sum(spec.weight_index for spec in self.active())
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"index weights sum to {total:.8f}, expected 1")
        for spec in self.active():
            if spec.weight_index > 0.15 + 1e-9:
                raise ValueError(f"benchmark {spec.id} exceeds 15%")
        platform_weights: dict[str, float] = {}
        for spec in self.active():
            platform_weights[spec.source_platform] = (
                platform_weights.get(spec.source_platform, 0.0) + spec.weight_index
            )
        for platform, weight in platform_weights.items():
            if weight > 0.30 + 1e-9:
                warnings.append(
                    f"delivery platform {platform} has {weight:.1%} weight; "
                    "underlying benchmark owners remain distinct"
                )
        return warnings


def load_index_config(path: str | Path) -> IndexConfig:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    benchmarks = {
        item["id"]: BenchmarkSpec(
            id=item["id"],
            title=item["title"],
            dimension=item["dimension"],
            status=item["status"],
            metric_type=item["metric_type"],
            chance_baseline=float(item.get("chance_baseline", 0)),
            source_platform=item["source_platform"],
            weight_index=float(item.get("weights", {}).get("index", 0)),
            special_transform=item.get("special_transform", ""),
            source_url=item.get("source_url", ""),
            notes=item.get("notes", ""),
        )
        for item in payload["benchmarks"]
    }
    config = IndexConfig(
        version=payload["version"],
        benchmarks=benchmarks,
        dimensions=payload["dimensions"],
        settings=payload["settings"],
    )
    config.validate()
    return config
