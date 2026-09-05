from __future__ import annotations

import json
import math
import re
from typing import Any

from ..identity import public_model_identity
from ..models import Observation
from .base import AdapterError, FetchResult, SourceAdapter


_FLIGHT_SCRIPT = re.compile(
    r"<script[^>]*>\s*self\.__next_f\.push\((.*?)\)\s*</script>",
    re.DOTALL,
)


def _flight_text(html: str) -> str:
    chunks: list[str] = []
    for match in _FLIGHT_SCRIPT.finditer(html):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, list) and len(payload) > 1 and isinstance(payload[1], str):
            chunks.append(payload[1])
    if not chunks:
        raise AdapterError("Artificial Analysis page has no readable Next Flight payload")
    return "".join(chunks)


def _json_value_after(text: str, key: str) -> Any:
    marker = json.dumps(key) + ":"
    position = text.find(marker)
    if position < 0:
        raise AdapterError(f"Artificial Analysis payload missing {key}")
    value_start = position + len(marker)
    while value_start < len(text) and text[value_start] in " \t\r\n":
        value_start += 1
    try:
        return json.JSONDecoder().raw_decode(text[value_start:])[0]
    except json.JSONDecodeError as exc:
        raise AdapterError(f"Artificial Analysis payload has invalid {key}") from exc


AA_SCORE_FIELDS = ("hle", "gpqa", "critpt", "lcr", "omniscience", "gdp_pdf")


def extract_aa_catalog_manifest(text: str) -> dict[str, str]:
    """Locate the public full-catalog asset used by AA's model selector."""
    manifest = _json_value_after(_flight_text(text), "manifest")
    if not isinstance(manifest, dict):
        raise AdapterError("Artificial Analysis full-catalog manifest is not an object")
    path, key = manifest.get("path"), manifest.get("key")
    if not isinstance(path, str) or not re.fullmatch(r"/data/[a-zA-Z0-9_.-]+", path):
        raise AdapterError("Artificial Analysis full-catalog path is invalid")
    if not isinstance(key, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", key):
        raise AdapterError("Artificial Analysis full-catalog decoding key is invalid")
    return {"path": path, "key": key}


def normalize_aa_row(row: dict[str, Any]) -> dict[str, Any]:
    """Map current AA camelCase records onto the frozen snake_case snapshot."""
    name = str(row.get("name") or row.get("short_name") or row.get("shortName") or "").strip()
    return {
        "name": name,
        "slug": str(row.get("slug") or "").strip(),
        "short_name": str(row.get("short_name") or row.get("shortName") or name).strip(),
        "release_date": str(row.get("release_date") or row.get("releaseDate") or ""),
        "deleted": bool(row.get("deleted") or row.get("deprecated")),
        "model_creators": row.get("model_creators") or row.get("creator") or {},
        "canonical_eval_token_counts": (
            row.get("canonical_eval_token_counts") or row.get("canonicalEvalTokenCounts") or {}
        ),
        **{field: row.get(field) for field in AA_SCORE_FIELDS},
        "gdp_pdf": row.get("gdp_pdf", row.get("gdpPdfAllPass")),
        "input_modality_image": row.get("input_modality_image", row.get("inputModalityImage")),
    }


def extract_aa_model_rows(text: str, payload_key: str = "defaultData") -> list[dict[str, Any]]:
    """Read a frozen JSON snapshot or a public AA HTML Flight payload."""
    stripped = text.lstrip()
    raw_rows: Any = None
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AdapterError("Artificial Analysis snapshot is not valid JSON") from exc
        if isinstance(payload, list):
            raw_rows = payload
        elif isinstance(payload, dict):
            for key in (payload_key, "initialModels", "models"):
                candidate = payload.get(key)
                if isinstance(candidate, list):
                    raw_rows = candidate
                    break
        if raw_rows is None:
            raise AdapterError("Artificial Analysis snapshot is not a model list")
    else:
        flight = _flight_text(text)
        last_error: AdapterError | None = None
        for key in (payload_key, "initialModels"):
            try:
                candidate = _json_value_after(flight, key)
            except AdapterError as exc:
                last_error = exc
                continue
            if isinstance(candidate, list) and candidate:
                raw_rows = candidate
                break
        if raw_rows is None:
            raise last_error or AdapterError("Artificial Analysis payload missing model list")
    if not isinstance(raw_rows, list):
        raise AdapterError("Artificial Analysis snapshot is not a model list")
    return [normalize_aa_row(row) for row in raw_rows if isinstance(row, dict)]


def _aa_notes(name: str, has_token_counts: bool) -> str:
    bits = ["AA public catalog score"]
    if "fallback" in name.lower():
        bits.append("published endpoint uses a fallback/composite run")
    if has_token_counts:
        bits.append("canonical token counts present")
    else:
        bits.append("token counts not published for this field")
    return "; ".join(bits) + "."


def _normal_interval(score_pct: float, sample_size: int | None) -> tuple[float | None, float | None]:
    if not sample_size or score_pct < 0:
        return None, None
    proportion = max(0.0, min(1.0, score_pct / 100.0))
    half = 1.96 * math.sqrt(proportion * (1.0 - proportion) / sample_size) * 100.0
    return max(0.0, score_pct - half), min(100.0, score_pct + half)


class ArtificialAnalysisHtmlAdapter(SourceAdapter):
    """Read public, server-embedded AA evaluation measurements.

    The public evaluation pages serialize measured models as ``defaultData``
    or, after AA's 2026-08 redesign, as ``initialModels``.  We only import a
    field when its canonical token-count record is present, which distinguishes
    an independently run AA evaluation from lab-claimed or absent values.
    """

    def parse(self, result: FetchResult) -> list[Observation]:
        try:
            text = result.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AdapterError(f"{self.source_id}: response is not UTF-8") from exc
        rows = extract_aa_model_rows(text, self.source.get("payload_key", "defaultData"))
        fields: dict[str, dict[str, Any]] = self.source.get("score_fields", {})
        observations: list[Observation] = []
        for row in rows:
            if not isinstance(row, dict) or row.get("deleted"):
                continue
            name = str(row.get("name") or row.get("short_name") or "").strip()
            slug = str(row.get("slug") or "").strip()
            release_date = str(row.get("release_date") or "")
            creator = row.get("model_creators") or {}
            provider = str(creator.get("slug") or creator.get("name") or "")
            if not name or not slug or not release_date:
                continue
            identity = public_model_identity(
                name=name,
                slug=slug,
                provider=provider,
                release_date=release_date,
            )
            alias = self.aliases.resolve(self.source_id, name)
            if alias:
                identity = {
                    **identity,
                    **{
                        key: alias[key]
                        for key in (
                            "provider",
                            "model_id",
                            "family_id",
                            "display_name",
                            "endpoint_date",
                            "reasoning_effort",
                            "protocol_compatible",
                            "mutable_alias",
                            "input_cost_per_million",
                            "output_cost_per_million",
                            "speed_tokens_per_second",
                            "context_window_tokens",
                        )
                        if alias.get(key) not in (None, "")
                    },
                }
            token_counts = row.get("canonical_eval_token_counts") or {}
            for benchmark_id, spec in fields.items():
                field = str(spec.get("field") or benchmark_id)
                value = row.get(field)
                if value is None:
                    continue
                token_key = str(spec.get("token_key") or field)
                has_token_counts = token_key in token_counts
                if spec.get("require_token_counts", True) and not has_token_counts:
                    continue
                unit = str(spec.get("unit", "proportion"))
                scale = float(spec.get("scale", 1.0))
                score = float(value) * scale
                sample_size = int(spec["sample_size"]) if spec.get("sample_size") else None
                score_pct = score if unit == "percent" else score * 100.0
                # Repeated attempts share tasks. Without task-level outcomes,
                # an independent-trials interval would overstate precision.
                ci_low, ci_high = _normal_interval(
                    score_pct, sample_size if spec.get("estimate_interval", True) else None
                )
                if unit != "percent" and ci_low is not None and ci_high is not None:
                    ci_low /= 100.0
                    ci_high /= 100.0
                modality = spec.get("modality", "text")
                if spec.get("modality_from_image_support"):
                    if not isinstance(row.get("input_modality_image"), bool):
                        raise AdapterError(f"{self.source_id}: missing image support for {slug}/{benchmark_id}")
                    modality = "multimodal" if row["input_modality_image"] else "text"
                observations.append(
                    Observation.from_mapping(
                        {
                            **identity,
                            "benchmark_id": benchmark_id,
                            "benchmark_version": spec["version"],
                            "raw_score": score,
                            "metric": spec.get("metric", "canonical"),
                            "source_id": self.source_id,
                            "source_model_name": name,
                            "source_url": spec.get("source_url") or self.source.get("public_url") or self.source.get("url"),
                            "source_tier": self.source.get("source_tier", "independent"),
                            "eval_date": result.retrieved_at[:10],
                            "retrieved_at": result.retrieved_at,
                            "split": spec.get("split", "default"),
                            "tool_mode": "none",
                            "modality": modality,
                            "protocol_hash": spec.get("protocol_hash", ""),
                            "raw_hash": result.sha256,
                            "ci_low": ci_low,
                            "ci_high": ci_high,
                            "sample_size": sample_size,
                            "protocol_compatible": True,
                            "notes": " ".join(filter(None, [
                                _aa_notes(name, has_token_counts), spec.get("notes", "")
                            ])),
                        }
                    )
                )
        return observations
