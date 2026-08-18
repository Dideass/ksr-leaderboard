from __future__ import annotations

import json
import re
from typing import Any

from ..identity import public_model_identity
from .base import AdapterError, FetchResult, SourceAdapter, parse_json_bytes


_EFFORT = (
    (r"\b(?:xhigh|extra[ -]?high)\b", "xhigh"),
    (r"\bmax(?:imum)?\b", "max"),
    (r"\bhigh\b", "high"),
    (r"\bmedium\b", "medium"),
    (r"\blow\b", "low"),
    (r"\b(?:minimal|none)\b", "none"),
)


def _effort_from_label(name: str) -> str:
    text = name.lower()
    for pattern, effort in _EFFORT:
        if re.search(pattern, text):
            return effort
    return ""


def _iso_date(value: Any) -> str:
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else ""


def _identity_name(display: str, provider: str) -> str:
    name = re.sub(r"\s*\([^)]*\)\s*$", "", display).strip() or display
    if provider.lower() == "anthropic" and re.match(r"^opus\b", name, re.I):
        name = "Claude " + name
    return name


def slim_arc_leaderboard(v2: dict[str, Any], models: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {str(item.get("id")): item for item in models if isinstance(item, dict)}
    rows = []
    for ev in v2.get("evaluations") or []:
        if not isinstance(ev, dict) or ev.get("score") is None:
            continue
        if ev.get("display") is False:
            continue
        model_id = str(ev.get("modelId") or "")
        meta = by_id.get(model_id, {})
        model_type = meta.get("modelType") or ev.get("modelType")
        if model_type != "CoT":
            continue
        provider = str(ev.get("providerDisplayName") or ev.get("providerId") or "")
        group = str(meta.get("modelGroup") or ev.get("modelGroup") or "")
        if provider == "Human" or group in {"Human", "Kaggle"}:
            continue
        display = str(ev.get("modelDisplayName") or meta.get("displayName") or model_id)
        rows.append(
            {
                "modelId": model_id,
                "displayName": display,
                "provider": provider,
                "score": ev["score"],
                "modelReleaseDate": ev.get("modelReleaseDate") or meta.get("modelReleaseDate"),
                "resultsUrl": ev.get("resultsUrl") or "",
            }
        )
    if not rows:
        raise AdapterError("ARC-AGI-2 snapshot has no verified CoT rows")
    return {
        "generated_at": v2.get("generatedAt"),
        "dataset": "v2_Semi_Private",
        "rows": rows,
    }


class ArcPrizeLeaderboardAdapter(SourceAdapter):
    """Import official ARC Prize verified CoT rows for ARC-AGI-2."""

    def parse(self, result: FetchResult) -> list:
        payload = parse_json_bytes(result.content)
        if not isinstance(payload, dict):
            raise AdapterError(f"{self.source_id}: expected a JSON object")
        if "rows" in payload:
            catalog = payload
        elif "evaluations" in payload:
            raise AdapterError(
                f"{self.source_id}: raw v2 payload needs slimming; refresh the frozen snapshot"
            )
        else:
            raise AdapterError(f"{self.source_id}: snapshot missing rows")
        rows = catalog.get("rows")
        if not isinstance(rows, list):
            raise AdapterError(f"{self.source_id}: rows is not a list")
        public_url = str(self.source.get("public_url") or "https://arcprize.org/leaderboard")
        unique: dict[tuple[str, str, str, str], Any] = {}
        for row in rows:
            if not isinstance(row, dict) or row.get("score") is None:
                continue
            display = str(row.get("displayName") or row.get("modelId") or "").strip()
            if not display:
                continue
            score = float(row["score"])
            score_pct = score * 100.0 if 0.0 <= score <= 1.0 else score
            released = _iso_date(row.get("modelReleaseDate"))
            results = str(row.get("resultsUrl") or "").strip()
            if results.startswith("/"):
                source_url = "https://arcprize.org" + results
            else:
                source_url = results or public_url
            identity = public_model_identity(
                name=display,
                slug=_identity_name(display, str(row.get("provider") or "")),
                provider=str(row.get("provider") or ""),
                release_date=released,
                explicit_effort=_effort_from_label(display),
            )
            item = self._observation(
                source_model_name=display,
                benchmark_id=str(self.source.get("benchmark_id") or "arc_agi_2"),
                benchmark_version=str(
                    self.source.get("benchmark_version") or "official-semi-private-120"
                ),
                raw_score=score_pct,
                metric=self.source.get("metric", "pass_rate"),
                retrieved_at=result.retrieved_at,
                raw_hash=result.sha256,
                eval_date=released or result.retrieved_at[:10],
                identity=identity,
            )
            item.source_url = source_url
            item.notes = (
                "Official ARC Prize verified CoT on the 120-task semi-private board; "
                "Custom, synthesis, refinement and Kaggle systems excluded."
            )
            key = (
                item.benchmark_id,
                item.benchmark_version,
                item.config_id,
                item.source_id,
            )
            previous = unique.get(key)
            if previous is None or item.raw_score > previous.raw_score:
                unique[key] = item
        return list(unique.values())
