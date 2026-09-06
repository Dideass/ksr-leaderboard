from __future__ import annotations

import csv
import io
import json
import gzip
import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from .adapters.artificial_analysis import AA_SCORE_FIELDS, extract_aa_catalog_manifest, extract_aa_model_rows
from .adapters.base import AdapterError
from .adapters.arc_prize import slim_arc_leaderboard


AA_KEEP_FIELDS = (
    "name",
    "slug",
    "short_name",
    "release_date",
    "deleted",
    "deprecated",
    "model_creators",
    "canonical_eval_token_counts",
    "input_modality_image",
    *AA_SCORE_FIELDS,
)


def _http_get(url: str, timeout_seconds: float) -> httpx.Response:
    headers = {
        "User-Agent": "KSR-Index/0.1 (+manual snapshot)",
        "Accept": "application/json,text/csv,text/html;q=0.9,*/*;q=0.5",
    }
    with httpx.Client(
        follow_redirects=True,
        timeout=timeout_seconds,
        headers=headers,
        trust_env=True,
    ) as client:
        response = client.get(url)
        response.raise_for_status()
        return response


def _resolve_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _freeze_aa_catalog(
    content: bytes, destination: Path, *, preserve_existing: bool = True
) -> dict[str, Any]:
    incoming = [
        {key: row.get(key) for key in AA_KEEP_FIELDS}
        for row in extract_aa_model_rows(content.decode("utf-8"))
        if row.get("slug")
    ]
    by_slug = {str(row["slug"]): row for row in incoming}
    merged_from_existing = 0
    if destination.is_file():
        previous = json.loads(destination.read_text(encoding="utf-8"))
        if preserve_existing and isinstance(previous, list) and len(previous) > max(32, len(by_slug) * 2):
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
        "gdp_pdf": sum(item.get("gdp_pdf") is not None for item in slim),
    }


def _decode_aa_catalog(content: bytes, key_hex: str) -> bytes:
    """Decode AA's public browser asset using its page-published key.

    Mirrors the website loader: AES-GCM, SHA-256(key)[:12] nonce, then gzip.
    This is the same catalog available through the public model selector.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    try:
        key = bytes.fromhex(key_hex)
        compressed = AESGCM(key).decrypt(hashlib.sha256(key).digest()[:12], content, None)
        decoded = gzip.decompress(compressed)
        payload = json.loads(decoded)
        if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
            raise ValueError("missing model catalog")
        if not payload["models"]:
            raise ValueError("empty model catalog")
    except Exception as exc:
        raise AdapterError("Artificial Analysis full catalog could not be decoded") from exc
    return decoded


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
        content = response.content
        if source.get("full_catalog", False):
            manifest = extract_aa_catalog_manifest(content.decode("utf-8"))
            catalog = _http_get(urljoin(url, manifest["path"]), timeout_seconds)
            content = _decode_aa_catalog(catalog.content, manifest["key"])
            rows = extract_aa_model_rows(content.decode("utf-8"))
            for benchmark_id, spec in source.get("score_fields", {}).items():
                field = spec["field"]
                token_key = spec.get("token_key", field)
                count = sum(not row.get("deleted") and row.get(field) is not None and token_key in (
                    row.get("canonical_eval_token_counts") or {}
                ) for row in rows)
                if count < spec.get("minimum_models", 1):
                    raise AdapterError(f"{source_id}: full catalog has too few measured rows for {benchmark_id}: {count}")
        extras = _freeze_aa_catalog(
            content, destination, preserve_existing=not source.get("full_catalog", False)
        )
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
