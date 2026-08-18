from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .models import Observation, ScoreRow, utc_now_iso


def ensure_directories(root: str | Path) -> None:
    base = Path(root)
    for relative in ("data/raw", "data/state", "artifacts/data", "artifacts/site"):
        (base / relative).mkdir(parents=True, exist_ok=True)


def load_observations(path: str | Path) -> list[Observation]:
    target = Path(path)
    if not target.exists():
        return []
    observations: list[Observation] = []
    with target.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                observations.append(Observation.from_mapping(json.loads(line)))
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"invalid observation at {target}:{line_number}: {exc}") from exc
    return observations


def observation_identity(observation: Observation) -> tuple[str, ...]:
    return (
        observation.benchmark_id,
        observation.benchmark_version,
        observation.source_id,
        observation.source_model_name or observation.model_id,
        observation.eval_date,
        observation.reasoning_effort,
        observation.split,
        observation.raw_hash,
    )


def merge_observations(
    existing: Iterable[Observation], incoming: Iterable[Observation]
) -> list[Observation]:
    merged = {observation_identity(item): item for item in existing}
    for item in incoming:
        merged[observation_identity(item)] = item
    return sorted(
        merged.values(),
        key=lambda item: (
            item.benchmark_id,
            item.provider,
            item.model_id,
            item.endpoint_date,
            item.reasoning_effort,
            item.retrieved_at,
        ),
    )


def write_observations(path: str | Path, observations: Iterable[Observation]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for observation in observations:
            handle.write(json.dumps(observation.to_dict(), ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def write_raw_snapshot(
    root: str | Path,
    source_id: str,
    content: bytes,
    content_type: str,
    sha256: str,
) -> Path:
    extension = ".json" if "json" in content_type else ".csv" if "csv" in content_type else ".bin"
    target = Path(root) / "data" / "raw" / source_id / f"{sha256}{extension}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(content)
    return target


def write_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def read_json(path: str | Path, default: Any = None) -> Any:
    target = Path(path)
    if not target.exists():
        return default
    return json.loads(target.read_text(encoding="utf-8"))


def write_score_exports(
    output_dir: str | Path,
    name: str,
    rows: list[ScoreRow],
) -> None:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    payload = [row.to_dict() for row in rows]
    write_json(directory / f"{name}.json", payload)
    flat_rows = []
    for row in rows:
        flat_rows.append(
            {
                "rank": row.rank,
                "entity_id": row.entity_id,
                "display_name": row.display_name,
                "provider": row.provider,
                "index_id": row.index_id,
                "index_version": row.index_version,
                "status": row.status,
                "point": row.point,
                "lower": row.lower,
                "upper": row.upper,
                "coverage": row.coverage,
                "imputed_weight": row.imputed_weight,
                "ci_low": row.ci_low,
                "ci_high": row.ci_high,
                "warning": row.warning,
                "release_date": row.release_date,
                "standard_error": row.standard_error,
                "confidence": row.confidence,
                "observed_benchmarks": row.observed_benchmarks,
                "observed_dimensions": row.observed_dimensions,
                "evidence_families": row.evidence_families,
                "anchor_comparisons": row.anchor_comparisons,
                "latent_ability": row.latent_ability,
                "as_of": row.as_of,
                "input_cost_per_million": row.input_cost_per_million,
                "output_cost_per_million": row.output_cost_per_million,
                "speed_tokens_per_second": row.speed_tokens_per_second,
                "context_window_tokens": row.context_window_tokens,
            }
        )
    fieldnames = list(flat_rows[0]) if flat_rows else [
        "rank",
        "entity_id",
        "display_name",
        "provider",
        "index_id",
        "index_version",
        "status",
        "point",
        "lower",
        "upper",
        "coverage",
        "imputed_weight",
        "ci_low",
        "ci_high",
        "warning",
        "release_date",
        "standard_error",
        "confidence",
        "observed_benchmarks",
        "observed_dimensions",
        "evidence_families",
        "anchor_comparisons",
        "latent_ability",
        "as_of",
        "input_cost_per_million",
        "output_cost_per_million",
        "speed_tokens_per_second",
        "context_window_tokens",
    ]
    with (directory / f"{name}.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(flat_rows)


def write_observations_parquet(
    path: str | Path, observations: list[Observation]
) -> tuple[bool, str]:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        frame = pd.DataFrame([item.to_dict() for item in observations])
        frame.to_parquet(target, index=False)
        return True, ""
    except (ImportError, ValueError) as exc:
        return False, str(exc)


def content_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def new_manifest_base(version: str) -> dict[str, Any]:
    return {"index_version": version, "generated_at": utc_now_iso()}
