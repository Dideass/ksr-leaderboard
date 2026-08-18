from __future__ import annotations

import hashlib
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ..models import Observation, utc_now_iso


class AdapterError(RuntimeError):
    pass


@dataclass(slots=True)
class FetchResult:
    source_id: str
    content: bytes
    content_type: str
    retrieved_at: str
    status_code: int
    etag: str = ""
    last_modified: str = ""

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


class AliasRegistry:
    def __init__(self, records: list[dict[str, str]]) -> None:
        self.records = {
            (record.get("source_id", "").strip(), record.get("source_model_name", "").strip()): record
            for record in records
            if record.get("source_model_name")
        }

    @classmethod
    def from_csv(cls, path: str | Path) -> "AliasRegistry":
        import csv

        target = Path(path)
        if not target.exists():
            return cls([])
        with target.open("r", encoding="utf-8-sig", newline="") as handle:
            return cls(list(csv.DictReader(handle)))

    def resolve(self, source_id: str, source_model_name: str) -> dict[str, str] | None:
        return self.records.get((source_id, source_model_name)) or self.records.get(
            ("*", source_model_name)
        )


class SourceAdapter(ABC):
    def __init__(self, source: dict[str, Any], aliases: AliasRegistry) -> None:
        self.source = source
        self.aliases = aliases
        self.source_id = source["id"]

    def fetch(self) -> FetchResult:
        path_value = self.source.get("path")
        if path_value:
            target = Path(path_value)
            if not target.is_file():
                raise AdapterError(f"{self.source_id}: local snapshot not found: {target}")
            suffix = target.suffix.lower()
            content_type = {
                ".json": "application/json",
                ".csv": "text/csv",
                ".html": "text/html",
                ".htm": "text/html",
            }.get(suffix, "application/octet-stream")
            return FetchResult(
                source_id=self.source_id,
                content=target.read_bytes(),
                content_type=content_type,
                retrieved_at=utc_now_iso(),
                status_code=200,
            )
        url = self.source.get("url")
        if not url:
            raise AdapterError(f"{self.source_id}: missing source path or URL")
        for key in ("ALL_PROXY", "all_proxy"):
            os.environ.pop(key, None)
        headers = {
            "User-Agent": "KSR-Index/0.1 (+private research index)",
            "Accept": self.source.get("accept", "application/json,text/csv;q=0.9,*/*;q=0.5"),
        }
        try:
            timeout_seconds = float(self.source.get("timeout_seconds", 30.0))
            with httpx.Client(
                follow_redirects=True,
                timeout=timeout_seconds,
                headers=headers,
            ) as client:
                response = client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AdapterError(f"{self.source_id}: fetch failed: {exc}") from exc
        return FetchResult(
            source_id=self.source_id,
            content=response.content,
            content_type=response.headers.get("content-type", ""),
            retrieved_at=utc_now_iso(),
            status_code=response.status_code,
            etag=response.headers.get("etag", ""),
            last_modified=response.headers.get("last-modified", ""),
        )

    @abstractmethod
    def parse(self, result: FetchResult) -> list[Observation]:
        raise NotImplementedError

    def validate(self, observations: list[Observation]) -> None:
        minimum_rows = int(self.source.get("minimum_rows", 1))
        if len(observations) < minimum_rows:
            raise AdapterError(
                f"{self.source_id}: parsed {len(observations)} rows, expected >= {minimum_rows}"
            )
        seen: set[tuple[str, str, str, str]] = set()
        for observation in observations:
            if not -100 <= observation.raw_score <= 100:
                raise AdapterError(
                    f"{self.source_id}: score outside supported range: {observation.raw_score}"
                )
            key = (
                observation.benchmark_id,
                observation.benchmark_version,
                observation.config_id,
                observation.source_id,
            )
            if key in seen:
                raise AdapterError(f"{self.source_id}: duplicate observation {key}")
            seen.add(key)

    def _model_fields(self, source_model_name: str) -> dict[str, Any]:
        alias = self.aliases.resolve(self.source_id, source_model_name)
        if alias:
            return {
                "provider": alias.get("provider", "unknown"),
                "model_id": alias.get("model_id", source_model_name),
                "family_id": alias.get("family_id", alias.get("model_id", source_model_name)),
                "display_name": alias.get("display_name", source_model_name),
                "endpoint_date": alias.get("endpoint_date", ""),
                "reasoning_effort": alias.get("reasoning_effort", "default"),
                "protocol_compatible": alias.get("protocol_compatible", "true"),
                "mutable_alias": alias.get("mutable_alias", "false"),
                "input_cost_per_million": alias.get("input_cost_per_million", ""),
                "output_cost_per_million": alias.get("output_cost_per_million", ""),
                "speed_tokens_per_second": alias.get("speed_tokens_per_second", ""),
                "context_window_tokens": alias.get("context_window_tokens", ""),
            }
        safe_name = source_model_name.strip()
        return {
            "provider": "unmapped",
            "model_id": safe_name,
            "family_id": safe_name,
            "display_name": safe_name,
            "endpoint_date": "",
            "reasoning_effort": "unknown",
            "protocol_compatible": False,
            "mutable_alias": False,
            "input_cost_per_million": None,
            "output_cost_per_million": None,
            "speed_tokens_per_second": None,
            "context_window_tokens": None,
        }

    def _observation(
        self,
        *,
        source_model_name: str,
        benchmark_id: str,
        benchmark_version: str,
        raw_score: float,
        metric: str,
        retrieved_at: str,
        raw_hash: str,
        eval_date: str | None = None,
        ci_low: float | None = None,
        ci_high: float | None = None,
        sample_size: int | None = None,
        split: str = "default",
        identity: dict[str, Any] | None = None,
    ) -> Observation:
        model = identity or self._model_fields(source_model_name)
        if str(model.get("mutable_alias", "false")).lower() in {"1", "true", "yes", "y"}:
            snapshot_date = retrieved_at[:10]
            model["model_id"] = f"{model['model_id']}@{snapshot_date}"
            model["endpoint_date"] = snapshot_date
            model["display_name"] = f"{model['display_name']} (snapshot {snapshot_date})"
        return Observation.from_mapping(
            {
                **model,
                "benchmark_id": benchmark_id,
                "benchmark_version": benchmark_version,
                "raw_score": raw_score,
                "metric": metric,
                "source_id": self.source_id,
                "source_model_name": source_model_name,
                "source_url": self.source.get("public_url") or self.source.get("url"),
                "source_tier": self.source.get("source_tier", "benchmark_host"),
                "eval_date": eval_date or self.source.get("eval_date") or retrieved_at[:10],
                "retrieved_at": retrieved_at,
                "tool_mode": self.source.get("tool_mode", "none"),
                "modality": self.source.get("modality", "text"),
                "protocol_hash": self.source.get("protocol_hash", ""),
                "raw_hash": raw_hash,
                "ci_low": ci_low,
                "ci_high": ci_high,
                "sample_size": sample_size,
                "split": split,
            }
        )


def build_adapter(source: dict[str, Any], aliases: AliasRegistry) -> SourceAdapter:
    adapter_type = source["adapter"]
    if adapter_type == "manual_csv":
        from .manual import ManualCsvAdapter

        return ManualCsvAdapter(source, aliases)
    if adapter_type == "curated_csv":
        from .curated_csv import CuratedLeaderboardCsvAdapter

        return CuratedLeaderboardCsvAdapter(source, aliases)
    if adapter_type == "kaggle_json":
        from .kaggle import KaggleLeaderboardAdapter

        return KaggleLeaderboardAdapter(source, aliases)
    if adapter_type == "wide_csv":
        from .wide_csv import WideCsvAdapter

        return WideCsvAdapter(source, aliases)
    if adapter_type == "category_mean_csv":
        from .wide_csv import CategoryMeanCsvAdapter

        return CategoryMeanCsvAdapter(source, aliases)
    if adapter_type == "normalized_json":
        from .normalized_json import NormalizedJsonAdapter

        return NormalizedJsonAdapter(source, aliases)
    if adapter_type == "matharena_parquet":
        from .matharena import MathArenaParquetAdapter

        return MathArenaParquetAdapter(source, aliases)
    if adapter_type == "artificial_analysis_html":
        from .artificial_analysis import ArtificialAnalysisHtmlAdapter

        return ArtificialAnalysisHtmlAdapter(source, aliases)
    if adapter_type == "vals_html":
        from .vals import ValsHtmlAdapter

        return ValsHtmlAdapter(source, aliases)
    if adapter_type == "arc_prize_json":
        from .arc_prize import ArcPrizeLeaderboardAdapter

        return ArcPrizeLeaderboardAdapter(source, aliases)
    raise AdapterError(f"unknown adapter type: {adapter_type}")


def parse_json_bytes(content: bytes) -> Any:
    try:
        return json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdapterError(f"invalid JSON payload: {exc}") from exc
