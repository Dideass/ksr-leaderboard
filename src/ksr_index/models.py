from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Mapping


SOURCE_PRIORITY = {
    "vendor": 1,
    "benchmark_author": 2,
    "independent": 3,
    "benchmark_host": 4,
}

REASONING_PRIORITY = {
    "unknown": -1,
    "none": 0,
    "default": 1,
    "low": 2,
    "medium": 3,
    "high": 4,
    "xhigh": 5,
    "max": 6,
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _float(value: Any) -> float | None:
    if value in (None, "", "null", "None"):
        return None
    return float(value)


def _bool(value: Any, default: bool = True) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


@dataclass(slots=True)
class Observation:
    benchmark_id: str
    benchmark_version: str
    model_id: str
    family_id: str
    provider: str
    raw_score: float
    metric: str
    source_id: str
    source_url: str
    eval_date: str
    retrieved_at: str = field(default_factory=utc_now_iso)
    split: str = "default"
    display_name: str = ""
    endpoint_date: str = ""
    reasoning_effort: str = "default"
    tool_mode: str = "none"
    modality: str = "text"
    source_tier: str = "benchmark_host"
    ci_low: float | None = None
    ci_high: float | None = None
    sample_size: int | None = None
    protocol_hash: str = ""
    raw_hash: str = ""
    protocol_compatible: bool = True
    mutable_alias: bool = False
    notes: str = ""
    source_model_name: str = ""
    input_cost_per_million: float | None = None
    output_cost_per_million: float | None = None
    speed_tokens_per_second: float | None = None
    context_window_tokens: int | None = None

    @property
    def config_id(self) -> str:
        endpoint = self.endpoint_date or "undated"
        return "::".join(
            [self.provider, self.model_id, endpoint, self.reasoning_effort]
        ).lower()

    @property
    def source_priority(self) -> int:
        return SOURCE_PRIORITY.get(self.source_tier, 0)

    @property
    def reasoning_priority(self) -> int:
        return REASONING_PRIORITY.get(self.reasoning_effort, -1)

    @property
    def date_key(self) -> tuple[int, int, int]:
        candidate = self.endpoint_date or self.eval_date
        try:
            parsed = date.fromisoformat(candidate[:10])
            return parsed.year, parsed.month, parsed.day
        except (TypeError, ValueError):
            return 0, 0, 0

    def is_eligible_native_no_tool(self) -> bool:
        return (
            self.protocol_compatible
            and self.modality in {"text", "multimodal", "vision", "grid-visual"}
            and self.tool_mode == "none"
            and bool(self.benchmark_version)
            and bool(self.endpoint_date)
            and self.reasoning_effort in REASONING_PRIORITY
            and self.reasoning_effort != "unknown"
            and bool(self.protocol_hash)
            and bool(self.source_url)
            and bool(self.eval_date)
        )

    def is_eligible_text_no_tool(self) -> bool:
        """Backward-compatible strict text-only predicate for diagnostics."""
        return self.modality == "text" and self.is_eligible_native_no_tool()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "Observation":
        required = [
            "benchmark_id",
            "benchmark_version",
            "model_id",
            "family_id",
            "provider",
            "raw_score",
            "metric",
            "source_id",
            "source_url",
            "eval_date",
        ]
        missing = [key for key in required if row.get(key) in (None, "")]
        if missing:
            raise ValueError(f"missing required observation fields: {', '.join(missing)}")
        sample_size = row.get("sample_size")
        return cls(
            benchmark_id=str(row["benchmark_id"]).strip(),
            benchmark_version=str(row["benchmark_version"]).strip(),
            model_id=str(row["model_id"]).strip(),
            family_id=str(row["family_id"]).strip(),
            provider=str(row["provider"]).strip(),
            raw_score=float(row["raw_score"]),
            metric=str(row["metric"]).strip(),
            source_id=str(row["source_id"]).strip(),
            source_url=str(row["source_url"]).strip(),
            eval_date=str(row["eval_date"]).strip(),
            retrieved_at=str(row.get("retrieved_at") or utc_now_iso()),
            split=str(row.get("split") or "default"),
            display_name=str(row.get("display_name") or row["model_id"]),
            endpoint_date=str(row.get("endpoint_date") or ""),
            reasoning_effort=str(row.get("reasoning_effort") or "default").lower(),
            tool_mode=str(row.get("tool_mode") or "none").lower(),
            modality=str(row.get("modality") or "text").lower(),
            source_tier=str(row.get("source_tier") or "benchmark_host"),
            ci_low=_float(row.get("ci_low")),
            ci_high=_float(row.get("ci_high")),
            sample_size=int(sample_size) if sample_size not in (None, "") else None,
            protocol_hash=str(row.get("protocol_hash") or ""),
            raw_hash=str(row.get("raw_hash") or ""),
            protocol_compatible=_bool(row.get("protocol_compatible"), True),
            mutable_alias=_bool(row.get("mutable_alias"), False),
            notes=str(row.get("notes") or ""),
            source_model_name=str(row.get("source_model_name") or row["model_id"]),
            input_cost_per_million=_float(row.get("input_cost_per_million")),
            output_cost_per_million=_float(row.get("output_cost_per_million")),
            speed_tokens_per_second=_float(row.get("speed_tokens_per_second")),
            context_window_tokens=(
                int(row["context_window_tokens"])
                if row.get("context_window_tokens") not in (None, "")
                else None
            ),
        )


@dataclass(slots=True, frozen=True)
class BenchmarkSpec:
    id: str
    title: str
    dimension: str
    status: str
    metric_type: str
    chance_baseline: float
    source_platform: str
    weight_index: float = 0.0
    special_transform: str = ""
    source_url: str = ""
    notes: str = ""

    @property
    def weights(self) -> dict[str, float]:
        return {"index": self.weight_index}


@dataclass(slots=True)
class ScoreRow:
    entity_id: str
    display_name: str
    provider: str
    index_id: str
    index_version: str
    status: str
    point: float | None
    lower: float
    upper: float
    coverage: float
    imputed_weight: float
    ci_low: float | None
    ci_high: float | None
    components: dict[str, dict[str, Any]]
    rank: int | None = None
    warning: str = ""
    release_date: str = ""
    standard_error: float | None = None
    confidence: str = "low"
    observed_benchmarks: int = 0
    observed_dimensions: int = 0
    evidence_families: int = 0
    anchor_comparisons: int = 0
    latent_ability: float | None = None
    as_of: str = field(default_factory=utc_now_iso)
    input_cost_per_million: float | None = None
    output_cost_per_million: float | None = None
    speed_tokens_per_second: float | None = None
    context_window_tokens: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
