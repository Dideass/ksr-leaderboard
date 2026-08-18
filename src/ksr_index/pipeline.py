from __future__ import annotations

import json
import hashlib
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .adapters import AdapterError, FetchResult, build_adapter
from .adapters.base import AliasRegistry
from .config import IndexConfig, load_index_config
from .consensus import score_consensus
from .governance import benchmark_governance_report
from .models import Observation, utc_now_iso
from .normalization import normalize_observation
from .site import render_site
from .storage import (
    content_hash,
    ensure_directories,
    load_observations,
    merge_observations,
    new_manifest_base,
    read_json,
    write_json,
    write_observations,
    write_observations_parquet,
    write_raw_snapshot,
    write_score_exports,
)


INGEST_SCHEMA_VERSION = 8


def _load_sources(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ingest_sources(
    root: Path,
    sources_path: Path,
    *,
    offline: bool = False,
) -> tuple[list[Observation], dict[str, Any], set[str]]:
    source_config = _load_sources(sources_path)
    aliases_path = root / source_config["aliases_path"]
    aliases = AliasRegistry.from_csv(aliases_path)
    aliases_sha256 = hashlib.sha256(aliases_path.read_bytes()).hexdigest()
    source_state_path = root / "data/state/sources.json"
    previous_state = read_json(source_state_path, {}) or {}
    next_state: dict[str, Any] = {}
    incoming: list[Observation] = []
    refreshed_source_ids: set[str] = set()
    for source in source_config["sources"]:
        source_id = source["id"]
        source_config_sha256 = hashlib.sha256(
            json.dumps(
                {"ingest_schema_version": INGEST_SCHEMA_VERSION, "source": source},
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        if source.get("path"):
            path = Path(source["path"])
            if not path.is_absolute():
                source = {**source, "path": str(root / path)}
        if not source.get("enabled", False):
            next_state[source_id] = {"status": "disabled"}
            continue
        if offline and source["adapter"] != "manual_csv":
            next_state[source_id] = {
                **previous_state.get(source_id, {}),
                "status": "offline_skipped",
            }
            continue
        adapter = build_adapter(source, aliases)
        try:
            prior = previous_state.get(source_id, {})
            metadata_changed = (
                prior.get("aliases_sha256") != aliases_sha256
                or prior.get("source_config_sha256") != source_config_sha256
            )
            cached_path = root / str(prior.get("raw_path", ""))
            reparsed_from_cache = bool(
                not source.get("path")
                and metadata_changed
                and prior.get("sha256")
                and prior.get("raw_path")
                and cached_path.is_file()
            )
            if reparsed_from_cache:
                fetched = FetchResult(
                    source_id=source_id,
                    content=cached_path.read_bytes(),
                    content_type=(
                        "application/json" if cached_path.suffix == ".json"
                        else "text/csv" if cached_path.suffix == ".csv"
                        else "application/octet-stream"
                    ),
                    retrieved_at=utc_now_iso(),
                    status_code=200,
                    etag=str(prior.get("etag", "")),
                    last_modified=str(prior.get("last_modified", "")),
                )
            else:
                fetched = adapter.fetch()
            raw_path = write_raw_snapshot(
                root, source_id, fetched.content, fetched.content_type, fetched.sha256
            )
            if (
                previous_state.get(source_id, {}).get("sha256") == fetched.sha256
                and previous_state.get(source_id, {}).get("aliases_sha256")
                == aliases_sha256
                and previous_state.get(source_id, {}).get("source_config_sha256")
                == source_config_sha256
            ):
                next_state[source_id] = {
                    **previous_state[source_id],
                    "status": "ok",
                    "checked_at": fetched.retrieved_at,
                    "consecutive_failures": 0,
                }
                continue
            observations = adapter.parse(fetched)
            adapter.validate(observations)
            previous_rows = int(previous_state.get(source_id, {}).get("row_count", 0))
            retained_fraction = float(source.get("minimum_retained_fraction", 0.7))
            if (
                previous_rows >= 10
                and len(observations) < previous_rows * retained_fraction
            ):
                raise AdapterError(
                    f"{source_id}: row count fell from {previous_rows} to "
                    f"{len(observations)} (< {retained_fraction:.0%})"
                )
            incoming.extend(observations)
            refreshed_source_ids.add(source_id)
            next_state[source_id] = {
                "status": "ok",
                "retrieved_at": fetched.retrieved_at,
                "sha256": fetched.sha256,
                "aliases_sha256": aliases_sha256,
                "source_config_sha256": source_config_sha256,
                "etag": fetched.etag,
                "last_modified": fetched.last_modified,
                "row_count": len(observations),
                "excluded_model_names": source.get("exclude_model_names", []),
                "exclusion_notes": source.get("exclusion_notes", {}),
                "reparsed_from_cache": reparsed_from_cache,
                "raw_path": str(raw_path.relative_to(root)),
                "consecutive_failures": 0,
            }
        except (AdapterError, OSError, ValueError) as exc:
            failures = int(previous_state.get(source_id, {}).get("consecutive_failures", 0)) + 1
            next_state[source_id] = {
                **previous_state.get(source_id, {}),
                "status": "blocked" if failures >= 2 else "stale",
                "last_error": str(exc),
                "consecutive_failures": failures,
            }
    write_json(source_state_path, next_state)
    return incoming, next_state, refreshed_source_ids


def build_artifacts(
    root: Path,
    config: IndexConfig,
    observations: list[Observation],
    source_state: dict[str, Any],
) -> dict[str, Any]:
    output_dir = root / "artifacts/data"
    result = score_consensus(observations, config)
    ranking_rows = result.rows
    write_score_exports(output_dir, "ranking", ranking_rows)
    for obsolete in ("strict.csv", "strict.json", "frontier.csv", "frontier.json", "chinese.csv", "chinese.json"):
        (output_dir / obsolete).unlink(missing_ok=True)
    parquet_ok, parquet_error = write_observations_parquet(
        output_dir / "observations.parquet", observations
    )

    scores_by_benchmark: dict[str, list[float]] = {}
    for observation in observations:
        spec = config.benchmarks.get(observation.benchmark_id)
        if (
            spec is None
            or spec.status not in {"active", "shadow"}
            or not observation.is_eligible_native_no_tool()
        ):
            continue
        item = normalize_observation(observation, spec)
        scores_by_benchmark.setdefault(observation.benchmark_id, []).append(item.score)
    governance = benchmark_governance_report(
        config.benchmarks.values(), scores_by_benchmark
    )
    method_hash = content_hash(
        {
            "version": config.version,
            "settings": config.settings,
            "benchmarks": [asdict(spec) for spec in config.benchmarks.values()],
        }
    )
    manifest = {
        **new_manifest_base(config.version),
        "config_warnings": config.validate(),
        "data_hash": content_hash([item.to_dict() for item in observations]),
        "method_hash": method_hash,
        "observation_count": len(observations),
        "eligible_observation_count": sum(
            item.is_eligible_native_no_tool() for item in observations
        ),
        "unmapped_models": sorted(
            {
                item.display_name
                for item in observations
                if item.provider == "unmapped" or not item.protocol_compatible
            }
        ),
        "leaderboard": {
            "row_count": len(ranking_rows),
            "ranked_count": sum(row.status == "ranked" for row in ranking_rows),
            "insufficient_count": sum(
                row.status == "insufficient" for row in ranking_rows
            ),
            **result.diagnostics,
        },
        "parquet": {"written": parquet_ok, "error": parquet_error},
        "sources": source_state,
        "governance": governance,
    }
    snapshot_id = (
        f"v{config.version}-{method_hash[:8]}-{manifest['data_hash'][:8]}"
    )
    manifest["snapshot_id"] = snapshot_id
    write_json(output_dir / "manifest.json", manifest)
    snapshot_dir = root / "data/state/snapshots" / snapshot_id
    if not snapshot_dir.exists():
        snapshot_dir.mkdir(parents=True, exist_ok=False)
        write_json(snapshot_dir / "manifest.json", manifest)
        write_json(snapshot_dir / "ranking.json", [row.to_dict() for row in ranking_rows])
    render_site(
        root=root,
        config=config,
        ranking_rows=ranking_rows,
        manifest=manifest,
    )
    return manifest


def run_pipeline(
    root: str | Path,
    *,
    index_config: str = "config/index.v1.json",
    sources_config: str = "config/sources.json",
    offline: bool = False,
) -> dict[str, Any]:
    project_root = Path(root).resolve()
    ensure_directories(project_root)
    config = load_index_config(project_root / index_config)
    state_path = project_root / "data/state/observations.jsonl"
    existing = load_observations(state_path)
    incoming, source_state, refreshed_source_ids = ingest_sources(
        project_root, project_root / sources_config, offline=offline
    )
    if refreshed_source_ids:
        existing = [
            item for item in existing if item.source_id not in refreshed_source_ids
        ]
    observations = merge_observations(existing, incoming)
    source_payload = _load_sources(project_root / sources_config)
    active_source_ids = {
        item["id"] for item in source_payload["sources"] if item.get("enabled", False)
    }
    # The benchmark and source manifests are the sole sources of truth.  Prune
    # rows left behind by deleted adapters instead of allowing a retired source
    # to keep influencing a still-active benchmark with the same ID.
    observations = [
        item
        for item in observations
        if item.benchmark_id in config.benchmarks and item.source_id in active_source_ids
    ]
    write_observations(state_path, observations)
    return build_artifacts(
        project_root,
        config,
        observations,
        source_state,
    )
