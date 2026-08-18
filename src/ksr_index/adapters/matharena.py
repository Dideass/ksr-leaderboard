from __future__ import annotations

import io
from collections import defaultdict
from statistics import fmean

import pyarrow.parquet as pq

from .base import AdapterError, FetchResult, SourceAdapter


class MathArenaParquetAdapter(SourceAdapter):
    """Aggregate an immutable MathArena output parquet.

    MathArena publishes several attempts for a problem.  KSR freezes the
    first answer only (``idx_answer=0``), averages repeated rows for the same
    problem/configuration, and then gives every problem equal weight.  This
    deliberately does not select a model's best run.
    """

    def parse(self, result: FetchResult):
        try:
            table = pq.read_table(io.BytesIO(result.content))
        except Exception as exc:  # pragma: no cover - backend-specific errors
            raise AdapterError(f"{self.source_id}: invalid parquet payload") from exc
        required = {"problem_idx", "model_name", "model_config", "idx_answer", "correct"}
        missing = required - set(table.column_names)
        if missing:
            raise AdapterError(f"{self.source_id}: parquet missing columns: {', '.join(sorted(missing))}")

        rows = table.to_pylist()
        per_problem: dict[tuple[str, str, str], list[float]] = defaultdict(list)
        for row in rows:
            try:
                if int(row.get("idx_answer")) != int(self.source.get("answer_index", 0)):
                    continue
            except (TypeError, ValueError):
                continue
            model_name = str(row.get("model_name") or "").strip()
            model_config = str(row.get("model_config") or "").strip()
            raw_problem_idx = row.get("problem_idx")
            problem_idx = "" if raw_problem_idx is None else str(raw_problem_idx).strip()
            if not model_name or not model_config or not problem_idx:
                continue
            value = row.get("correct")
            if isinstance(value, bool):
                score = float(value)
            else:
                try:
                    score = float(value)
                except (TypeError, ValueError):
                    continue
            if score not in (0.0, 1.0):
                raise AdapterError(f"{self.source_id}: correct must be boolean/0/1")
            per_problem[(model_name, model_config, problem_idx)].append(score)

        grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
        for (model_name, model_config, _), values in per_problem.items():
            grouped[(model_name, model_config)].append(fmean(values))
        observations = []
        for (model_name, model_config), problem_scores in grouped.items():
            observations.append(self._observation(
                source_model_name=model_name,
                benchmark_id=self.source["benchmark_id"],
                benchmark_version=self.source["benchmark_version"],
                raw_score=fmean(problem_scores),
                metric="pass_rate",
                retrieved_at=result.retrieved_at,
                raw_hash=result.sha256,
                sample_size=len(problem_scores),
                split=self.source.get("split", "default"),
            ))
            # Keep the provider/endpoint identity from the base-model alias,
            # while making the exact MathArena configuration part of the
            # strict configuration key.  An unmapped base model remains
            # ineligible rather than receiving guessed endpoint metadata.
            observations[-1].model_id = f"{observations[-1].model_id}::{model_config}"
            observations[-1].display_name = f"{observations[-1].display_name} [{model_config}]"
            observations[-1].notes = (
                f"MathArena frozen first-answer aggregate; model_name={model_name}; "
                f"model_config={model_config}; answer_index={self.source.get('answer_index', 0)}; "
                f"problems={len(problem_scores)}"
            )
        return observations
