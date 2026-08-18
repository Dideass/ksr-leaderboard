from __future__ import annotations

import html
import json
import re
from typing import Any

from ..identity import public_model_identity
from .base import AdapterError, FetchResult, SourceAdapter, parse_json_bytes


_ISO_DATE = re.compile(r"(20\d{2}-\d{2}-\d{2})")
_COMPACT_DATE = re.compile(r"(20\d{2})(\d{2})(\d{2})")


def _decode_astro(value: Any) -> Any:
    if not isinstance(value, list) or len(value) != 2 or not isinstance(value[0], int):
        if isinstance(value, list):
            return [_decode_astro(item) for item in value]
        if isinstance(value, dict):
            return {key: _decode_astro(item) for key, item in value.items()}
        return value
    kind, payload = value
    if kind == 0:
        return _decode_astro(payload)
    if kind == 1:
        return [_decode_astro(item) for item in payload]
    return payload


def extract_vals_benchmark_view(text: str) -> dict[str, Any]:
    match = re.search(
        r'<astro-island[^>]+component-url="/_astro/BenchmarkView\.[^"]+"[^>]*props="([^"]*)"',
        text,
    )
    if not match:
        raise AdapterError("Vals page has no BenchmarkView payload")
    try:
        encoded = json.loads(html.unescape(match.group(1)))
    except json.JSONDecodeError as exc:
        raise AdapterError("Vals BenchmarkView props are not valid JSON") from exc
    data = _decode_astro(encoded)
    view = data.get("benchmarkView") if isinstance(data, dict) else None
    if not isinstance(view, dict):
        raise AdapterError("Vals BenchmarkView payload is missing")
    payload = view.get("default") if isinstance(view.get("default"), dict) else view
    if not isinstance(payload.get("tasks"), dict):
        raise AdapterError("Vals BenchmarkView has no task table")
    return payload


def slim_vals_leaderboard(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("metadata") or {}
    overall = (payload.get("tasks") or {}).get("overall") or {}
    if not isinstance(overall, dict):
        raise AdapterError("Vals overall table is not an object")
    models = []
    for model_id, row in overall.items():
        if not isinstance(row, dict) or row.get("accuracy") is None:
            continue
        models.append(
            {
                "id": str(model_id),
                "provider": str(row.get("provider") or ""),
                "accuracy": row["accuracy"],
                "stderr": row.get("stderr"),
                "reasoning_effort": row.get("reasoning_effort"),
                "compute_effort": row.get("compute_effort"),
            }
        )
    if not models:
        raise AdapterError("Vals overall table has no scored models")
    return {
        "updated": metadata.get("updated"),
        "benchmark": metadata.get("benchmark_id") or "mmlu_pro",
        "models": models,
    }


def _display_name(model_id: str) -> str:
    slug = model_id.rsplit("/", 1)[-1].replace("_", "-")
    parts = [part for part in slug.split("-") if part]
    pretty: list[str] = []
    for part in parts:
        lower = part.lower()
        if lower == "gpt":
            pretty.append("GPT")
        elif lower in {"glm", "lcr"}:
            pretty.append(part.upper())
        elif re.fullmatch(r"\d+(?:\.\d+)?", part):
            pretty.append(part)
        else:
            pretty.append(part[:1].upper() + part[1:])
    return " ".join(pretty) or model_id


def _release_date(model_id: str, fallback: str) -> str:
    iso = _ISO_DATE.search(model_id)
    if iso:
        return iso.group(1)
    compact = _COMPACT_DATE.search(model_id.replace("-", ""))
    if compact:
        return f"{compact.group(1)}-{compact.group(2)}-{compact.group(3)}"
    return fallback[:10]


def _explicit_effort(row: dict[str, Any]) -> str:
    raw = row.get("reasoning_effort")
    if raw in (None, "", "None"):
        raw = row.get("compute_effort")
    if raw in (None, "", "None"):
        return ""
    text = str(raw).strip().lower()
    try:
        value = float(text)
    except ValueError:
        return text
    if value >= 0.9:
        return "max"
    if value >= 0.6:
        return "high"
    if value >= 0.3:
        return "medium"
    return "low"


class ValsHtmlAdapter(SourceAdapter):
    """Read a Vals.ai public benchmark page or a frozen slim JSON snapshot."""

    def parse(self, result: FetchResult) -> list:
        try:
            text = result.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AdapterError(f"{self.source_id}: response is not UTF-8") from exc
        stripped = text.lstrip()
        if stripped.startswith("{") or stripped.startswith("["):
            payload = parse_json_bytes(result.content)
            if isinstance(payload, dict) and "models" in payload:
                catalog = payload
            elif isinstance(payload, dict):
                catalog = slim_vals_leaderboard(payload.get("benchmarkView") or payload)
            else:
                raise AdapterError(f"{self.source_id}: unexpected JSON snapshot")
        else:
            catalog = slim_vals_leaderboard(extract_vals_benchmark_view(text))
        models = catalog.get("models")
        if not isinstance(models, list):
            raise AdapterError(f"{self.source_id}: snapshot has no model list")
        updated = str(catalog.get("updated") or self.source.get("eval_date") or result.retrieved_at[:10])
        benchmark_id = str(self.source.get("benchmark_id") or catalog.get("benchmark") or "mmlu_pro")
        version = str(self.source.get("benchmark_version") or f"vals-{updated}")
        sample_size = int(self.source["sample_size"]) if self.source.get("sample_size") else None
        observations = []
        for row in models:
            if not isinstance(row, dict):
                continue
            model_id = str(row.get("id") or "").strip()
            accuracy = row.get("accuracy")
            if not model_id or accuracy is None:
                continue
            score = float(accuracy)
            stderr = row.get("stderr")
            ci_low = ci_high = None
            if stderr not in (None, ""):
                half = 1.96 * float(stderr)
                ci_low = max(0.0, score - half)
                ci_high = min(100.0, score + half)
            display = _display_name(model_id)
            effort = _explicit_effort(row)
            identity = public_model_identity(
                name=display,
                slug=model_id.rsplit("/", 1)[-1],
                provider=str(row.get("provider") or ""),
                release_date=_release_date(model_id, updated),
                explicit_effort=effort,
            )
            observations.append(
                self._observation(
                    source_model_name=model_id,
                    benchmark_id=benchmark_id,
                    benchmark_version=version,
                    raw_score=score,
                    metric=self.source.get("metric", "canonical"),
                    retrieved_at=result.retrieved_at,
                    raw_hash=result.sha256,
                    eval_date=updated,
                    ci_low=ci_low,
                    ci_high=ci_high,
                    sample_size=sample_size,
                    identity=identity,
                )
            )
        for item in observations:
            item.notes = (
                "Vals.ai 5-shot chain-of-thought run of the official MMLU-Pro protocol; "
                "no external tools."
            )
        return observations
