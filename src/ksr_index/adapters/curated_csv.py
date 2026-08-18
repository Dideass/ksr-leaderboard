from __future__ import annotations

import csv
from io import StringIO

from ..models import Observation, utc_now_iso
from ..identity import public_model_identity
from .base import AdapterError, FetchResult, SourceAdapter


class CuratedLeaderboardCsvAdapter(SourceAdapter):
    """Import an audited, long-form leaderboard CSV without filling protocol gaps.

    The audit files deliberately carry ``reasoning_effort`` and ``tool_mode``.
    Unknown/not_reported values are retained in the observation and therefore
    cannot become score eligible accidentally. Aliases may supply stable model
    identity and an explicitly documented endpoint date, but never replace a
    non-empty protocol value from the audited row.
    """

    def fetch(self) -> FetchResult:
        from pathlib import Path

        path = Path(self.source["path"])
        if not path.exists():
            raise AdapterError(f"{self.source_id}: curated CSV not found: {path}")
        return FetchResult(
            source_id=self.source_id,
            content=path.read_bytes(),
            content_type="text/csv",
            retrieved_at=utc_now_iso(),
            status_code=200,
        )

    def parse(self, result: FetchResult) -> list[Observation]:
        rows = list(csv.DictReader(StringIO(result.content.decode("utf-8-sig"))))
        required = {"benchmark_id", "model_display", "score_pct", "source_url", "as_of"}
        if rows and not required.issubset(rows[0]):
            missing = sorted(required - set(rows[0]))
            raise AdapterError(f"{self.source_id}: curated CSV missing columns: {', '.join(missing)}")
        observations: list[Observation] = []
        for line_number, row in enumerate(rows, 2):
            if not row.get("model_display", "").strip():
                continue
            try:
                score = float(row["score_pct"])
            except (TypeError, ValueError) as exc:
                raise AdapterError(f"{self.source_id}: invalid score at row {line_number}") from exc
            source_model_name = row["model_display"].strip()
            model = self._model_fields(source_model_name)
            if model.get("provider") == "unmapped" and self.source.get("infer_public_identity", False):
                inferred_date = (
                    row.get("endpoint_date")
                    or self.source.get("endpoint_date")
                    or row.get("as_of")
                    or ""
                )
                model = public_model_identity(
                    name=source_model_name,
                    provider=row.get("provider", ""),
                    release_date=inferred_date,
                    explicit_effort=row.get("reasoning_effort", ""),
                )
            # Audit-row protocol fields are authoritative. Empty fields can use
            # a configured source default; aliases do not silently upgrade them.
            effort = (
                row.get("reasoning_effort")
                or self.source.get("reasoning_effort")
                or (
                    model.get("reasoning_effort")
                    if self.source.get("infer_effort_from_identity", False)
                    else ""
                )
                or "unknown"
            ).strip().lower()
            if effort == "thinking":
                effort = "default"
            tool_mode = (row.get("tool_mode") or self.source.get("tool_mode") or "unknown").strip().lower()
            modality = (row.get("modality") or self.source.get("modality") or "text").strip().lower()
            endpoint_date = (row.get("endpoint_date") or model.get("endpoint_date") or "").strip()
            protocol_hash = (row.get("protocol_hash") or self.source.get("protocol_hash") or "").strip()
            ci_half = row.get("ci_half_width_pct")
            ci_low = ci_high = None
            if ci_half not in (None, ""):
                half = float(ci_half)
                ci_low, ci_high = max(0.0, score - half), min(100.0, score + half)
            observations.append(Observation.from_mapping({
                **model,
                "benchmark_id": row["benchmark_id"].strip(),
                "benchmark_version": (row.get("version") or row.get("benchmark_version") or "").strip(),
                "raw_score": score,
                "metric": self.source.get("metric", "canonical"),
                "source_id": self.source_id,
                "source_model_name": source_model_name,
                "source_url": row["source_url"].strip(),
                "source_tier": self.source.get("source_tier", "benchmark_author"),
                "eval_date": row["as_of"].strip(),
                "retrieved_at": result.retrieved_at,
                "split": row.get("split") or "default",
                "endpoint_date": endpoint_date,
                "reasoning_effort": effort,
                "tool_mode": tool_mode,
                "modality": modality,
                "protocol_hash": protocol_hash,
                "raw_hash": result.sha256,
                "ci_low": ci_low,
                "ci_high": ci_high,
                "protocol_compatible": str(model.get("protocol_compatible", "true")).lower() not in {"false", "0", "no"},
                "notes": row.get("protocol_note", "").strip(),
            }))
        return observations

    def validate(self, observations: list[Observation]) -> None:
        if observations:
            super().validate(observations)
