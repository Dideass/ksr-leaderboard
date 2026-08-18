from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .base import AdapterError, FetchResult, SourceAdapter, parse_json_bytes


MODEL_KEYS = ("modelName", "model_name", "model", "name", "displayName")


def _nested_value(row: dict[str, Any], path: str) -> Any:
    value: Any = row
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def _find_rows(payload: Any, score_path: str) -> list[dict[str, Any]]:
    candidates: list[list[dict[str, Any]]] = []

    def visit(value: Any) -> None:
        if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            if any(_nested_value(item, score_path) is not None for item in value):
                candidates.append(value)
        if isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return max(candidates, key=len) if candidates else []


def _model_name(row: dict[str, Any], configured_path: str | None = None) -> str:
    if configured_path:
        value = _nested_value(row, configured_path)
        if isinstance(value, dict):
            value = value.get("name") or value.get("displayName")
        if value:
            return str(value)
    for key in MODEL_KEYS:
        value = row.get(key)
        if isinstance(value, dict):
            value = value.get("name") or value.get("displayName")
        if value:
            return str(value)
    return ""


class KaggleLeaderboardAdapter(SourceAdapter):
    def parse(self, result: FetchResult):
        payload = parse_json_bytes(result.content)
        if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
            kaggle_rows = self._parse_benchmark_rows(payload["rows"], result)
            if kaggle_rows:
                return kaggle_rows

        score_path = self.source.get("score_path", "score")
        rows = _find_rows(payload, score_path)
        if not rows:
            raise AdapterError(
                f"{self.source_id}: could not locate leaderboard rows for {score_path}"
            )
        observations = []
        excluded = {str(value) for value in self.source.get("exclude_model_names", [])}
        for row in rows:
            source_model_name = _model_name(row, self.source.get("model_path"))
            if source_model_name in excluded:
                continue
            score = _nested_value(row, score_path)
            if not source_model_name or score in (None, ""):
                continue
            ci_low = _nested_value(row, self.source.get("ci_low_path", "ciLow"))
            ci_high = _nested_value(row, self.source.get("ci_high_path", "ciHigh"))
            observations.append(
                self._observation(
                    source_model_name=source_model_name,
                    benchmark_id=self.source["benchmark_id"],
                    benchmark_version=self.source["benchmark_version"],
                    raw_score=float(score),
                    metric=self.source.get("metric", "canonical"),
                    retrieved_at=result.retrieved_at,
                    raw_hash=result.sha256,
                    ci_low=float(ci_low) if ci_low not in (None, "") else None,
                    ci_high=float(ci_high) if ci_high not in (None, "") else None,
                    sample_size=self.source.get("sample_size"),
                    split=self.source.get("split", "default"),
                )
            )
        return observations

    def _parse_benchmark_rows(self, rows, result: FetchResult):
        """Parse Kaggle's public Benchmarks API taskResults representation."""
        observations = []
        configured_task = self.source.get("task_name")
        excluded = {str(value) for value in self.source.get("exclude_model_names", [])}
        for row in rows:
            if not isinstance(row, dict):
                continue
            source_model_name = row.get("modelVersionName") or row.get("modelVersionSlug")
            if not source_model_name:
                continue
            if str(source_model_name) in excluded or str(row.get("modelVersionSlug", "")) in excluded:
                continue
            task_results = row.get("taskResults")
            if not isinstance(task_results, list):
                continue
            for task in task_results:
                if not isinstance(task, dict):
                    continue
                if configured_task and task.get("benchmarkTaskName") != configured_task:
                    continue
                task_result = task.get("result") or {}
                numeric = task_result.get("numericResult") or {}
                score = numeric.get("value")
                if score in (None, ""):
                    continue
                task_version = task.get("taskVersion")
                configured_version = self.source.get("benchmark_version", "current")
                benchmark_version = (
                    f"v{task_version}"
                    if task_version is not None and configured_version in {"auto", "current"}
                    else configured_version
                )
                half_width = numeric.get("confidenceInterval")
                ci_low = ci_high = None
                if numeric.get("hasConfidenceInterval") and half_width not in (None, ""):
                    ci_low = max(0.0, float(score) - float(half_width))
                    ci_high = min(1.0, float(score) + float(half_width))
                eval_date = task_result.get("evaluationDate")
                if eval_date:
                    eval_date = str(eval_date)[:10]
                observation = self._observation(
                    source_model_name=str(source_model_name),
                    benchmark_id=self.source["benchmark_id"],
                    benchmark_version=benchmark_version,
                    raw_score=float(score),
                    metric=self.source.get("metric", "canonical"),
                    retrieved_at=result.retrieved_at,
                    raw_hash=result.sha256,
                    eval_date=eval_date,
                    ci_low=ci_low,
                    ci_high=ci_high,
                    sample_size=self.source.get("sample_size"),
                    split=self.source.get("split", "default"),
                )
                if task_version is not None:
                    base_hash = self.source.get("protocol_hash", "kaggle-benchmark")
                    observation.protocol_hash = f"{base_hash}-v{task_version}"
                observations.append(observation)
                break
        return observations
