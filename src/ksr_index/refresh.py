from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
from typing import Any

import httpx

from .adapters.artificial_analysis import extract_aa_model_rows
from .adapters.base import AdapterError
from .adapters.arc_prize import slim_arc_leaderboard
from .adapters.vals import extract_vals_benchmark_view, slim_vals_leaderboard


AA_KEEP_FIELDS = (
    "name",
    "slug",
    "short_name",
    "release_date",
    "deleted",
    "model_creators",
    "canonical_eval_token_counts",
    "hle",
    "gpqa",
    "critpt",
    "lcr",
    "omniscience",
)


def _http_get(url: str, timeout_seconds: float) -> httpx.Response:
    for key in list(os.environ):
        if "proxy" in key.lower():
            os.environ.pop(key, None)
    headers = {
        "User-Agent": "KSR-Index/0.1 (+manual snapshot)",
        "Accept": "application/json,text/csv,text/html;q=0.9,*/*;q=0.5",
    }
    with httpx.Client(
        follow_redirects=True,
        timeout=timeout_seconds,
        headers=headers,
        trust_env=False,
    ) as client:
        response = client.get(url)
        response.raise_for_status()
        return response


def _resolve_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _freeze_aa_catalog(content: bytes, destination: Path) -> dict[str, Any]:
    incoming = [
        {key: row.get(key) for key in AA_KEEP_FIELDS}
        for row in extract_aa_model_rows(content.decode("utf-8"))
        if row.get("slug")
    ]
    by_slug = {str(row["slug"]): row for row in incoming}
    merged_from_existing = 0
    if destination.is_file():
        previous = json.loads(destination.read_text(encoding="utf-8"))
        if isinstance(previous, list) and len(previous) > max(32, len(by_slug) * 2):
            merged = {
                str(row.get("slug")): {key: row.get(key) for key in AA_KEEP_FIELDS}
                for row in previous
                if isinstance(row, dict) and row.get("slug")
            }
            merged_from_existing = len(merged)
            merged.update(by_slug)
            slim = list(merged.values())
        else:
            slim = list(by_slug.values())
    else:
        slim = list(by_slug.values())
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(slim, ensure_ascii=False), encoding="utf-8")
    return {
        "models": len(slim),
        "incoming": len(by_slug),
        "merged_from_existing": merged_from_existing,
        "hle": sum(item.get("hle") is not None for item in slim),
        "gpqa": sum(item.get("gpqa") is not None for item in slim),
        "critpt": sum(item.get("critpt") is not None for item in slim),
        "omniscience": sum(item.get("omniscience") is not None for item in slim),
    }


def _freeze_vals_mmlu_pro(content: bytes, destination: Path) -> dict[str, Any]:
    text = content.decode("utf-8")
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        payload = json.loads(text)
        catalog = (
            payload
            if isinstance(payload, dict) and "models" in payload
            else slim_vals_leaderboard(payload.get("benchmarkView") or payload)
        )
    else:
        catalog = slim_vals_leaderboard(extract_vals_benchmark_view(text))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
    return {
        "models": len(catalog.get("models") or []),
        "updated": catalog.get("updated"),
    }


def _freeze_arc_agi_2(content: bytes, destination: Path, timeout_seconds: float) -> dict[str, Any]:
    v2 = json.loads(content.decode("utf-8"))
    models_response = _http_get(
        "https://arcprize.org/media/data/models.json", timeout_seconds
    )
    models = json.loads(models_response.content.decode("utf-8"))
    if not isinstance(v2, dict) or not isinstance(models, list):
        raise AdapterError("ARC Prize snapshot is not the official leaderboard pair")
    catalog = slim_arc_leaderboard(v2, models)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
    return {"models": len(catalog["rows"]), "generated_at": catalog.get("generated_at")}


def refresh_source(root: Path, source: dict[str, Any]) -> dict[str, Any]:
    source_id = source["id"]
    url = source.get("url")
    path_value = source.get("path")
    if not url:
        raise AdapterError(f"{source_id}: no remote URL to refresh")
    if not path_value:
        raise AdapterError(f"{source_id}: no local snapshot path")
    destination = _resolve_path(root, path_value)
    timeout_seconds = float(source.get("timeout_seconds", 60.0))
    response = _http_get(url, timeout_seconds)
    extras: dict[str, Any] = {}
    if source_id == "aa_public_measurements":
        extras = _freeze_aa_catalog(response.content, destination)
    elif source_id == "vals_mmlu_pro":
        extras = _freeze_vals_mmlu_pro(response.content, destination)
    elif source_id == "arc_agi_2_verified_cot":
        extras = _freeze_arc_agi_2(response.content, destination, timeout_seconds)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(response.content)
        if destination.suffix.lower() == ".csv":
            extras["rows"] = len(list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig")))))
    return {
        "source_id": source_id,
        "url": url,
        "path": str(destination.relative_to(root)) if destination.is_relative_to(root) else str(destination),
        "bytes": destination.stat().st_size,
        **extras,
    }


def refreshable_sources(source_config: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        source
        for source in source_config["sources"]
        if source.get("enabled", False) and source.get("url") and source.get("path")
    ]
