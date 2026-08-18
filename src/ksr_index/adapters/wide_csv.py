from __future__ import annotations

import csv
from io import StringIO
from statistics import fmean

from ..identity import public_model_identity
from .base import AdapterError, FetchResult, SourceAdapter


class WideCsvAdapter(SourceAdapter):
    def parse(self, result: FetchResult):
        text = result.content.decode("utf-8-sig")
        rows = list(csv.DictReader(StringIO(text)))
        model_column = self.source.get("model_column", "model")
        columns: dict[str, str] = self.source.get("score_columns", {})
        observations = []
        for row in rows:
            source_model_name = row.get(model_column, "").strip()
            if not source_model_name:
                continue
            for benchmark_id, column in columns.items():
                value = row.get(column)
                if value in (None, "", "-"):
                    continue
                try:
                    score = float(str(value).replace("%", "").strip())
                except ValueError as exc:
                    raise AdapterError(
                        f"{self.source_id}: non-numeric {column} value {value!r}"
                    ) from exc
                observations.append(
                    self._observation(
                        source_model_name=source_model_name,
                        benchmark_id=benchmark_id,
                        benchmark_version=self.source["benchmark_version"],
                        raw_score=score,
                        metric=self.source.get("metric", "canonical"),
                        retrieved_at=result.retrieved_at,
                        raw_hash=result.sha256,
                        split=self.source.get("split", "default"),
                    )
                )
        return observations


class CategoryMeanCsvAdapter(SourceAdapter):
    """Aggregate a frozen task-level CSV into pre-registered category means."""

    def parse(self, result: FetchResult):
        text = result.content.decode("utf-8-sig")
        rows = list(csv.DictReader(StringIO(text)))
        model_column = self.source.get("model_column", "model")
        groups: dict[str, list[str]] = self.source.get("category_columns", {})
        observations = []
        infer_identity = bool(self.source.get("infer_public_identity", False))
        for row in rows:
            source_model_name = row.get(model_column, "").strip()
            if not source_model_name:
                continue
            inferred = None
            if infer_identity and self.aliases.resolve(self.source_id, source_model_name) is None:
                inferred = public_model_identity(
                    name=source_model_name,
                    slug=source_model_name,
                    release_date=str(self.source.get("eval_date") or ""),
                )
            for benchmark_id, columns in groups.items():
                values = []
                for column in columns:
                    value = row.get(column)
                    if value in (None, "", "-"):
                        continue
                    try:
                        values.append(float(str(value).replace("%", "").strip()))
                    except ValueError as exc:
                        raise AdapterError(
                            f"{self.source_id}: non-numeric {column} value {value!r}"
                        ) from exc
                if len(values) != len(columns):
                    raise AdapterError(
                        f"{self.source_id}: incomplete {benchmark_id} category for "
                        f"{source_model_name} ({len(values)}/{len(columns)})"
                    )
                observations.append(
                    self._observation(
                        source_model_name=source_model_name,
                        benchmark_id=benchmark_id,
                        benchmark_version=self.source["benchmark_version"],
                        raw_score=fmean(values),
                        metric=self.source.get("metric", "canonical"),
                        retrieved_at=result.retrieved_at,
                        raw_hash=result.sha256,
                        eval_date=self.source.get("eval_date"),
                        split=self.source.get("split", "default"),
                        identity=inferred,
                    )
                )
        return observations
