from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from .adapters.base import AliasRegistry
from .adapters.manual import ManualCsvAdapter
from .config import load_index_config
from .identity import public_model_identity
from .models import utc_now_iso
from .pipeline import build_artifacts, run_pipeline
from .refresh import refresh_source, refreshable_sources
from .storage import load_observations, read_json


MANUAL_FIELDS = [
    "benchmark_id",
    "benchmark_version",
    "split",
    "model_id",
    "family_id",
    "provider",
    "display_name",
    "endpoint_date",
    "reasoning_effort",
    "tool_mode",
    "modality",
    "raw_score",
    "metric",
    "ci_low",
    "ci_high",
    "sample_size",
    "source_id",
    "source_url",
    "source_tier",
    "eval_date",
    "retrieved_at",
    "protocol_hash",
    "raw_hash",
    "protocol_compatible",
    "mutable_alias",
    "notes",
    "source_model_name",
    "input_cost_per_million",
    "output_cost_per_million",
    "speed_tokens_per_second",
    "context_window_tokens",
]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ksr", description="Knowledge, Science, Reasoning leaderboard"
    )
    parser.add_argument("--root", default=".", help="project root")
    subparsers = parser.add_subparsers(dest="command", required=True)

    update = subparsers.add_parser(
        "update",
        help="re-ingest local snapshots and rebuild artifacts (no network)",
    )
    update.add_argument(
        "--offline",
        action="store_true",
        help="only read the manual observations CSV",
    )

    build = subparsers.add_parser("build", help="build artifacts from saved observations")

    refresh = subparsers.add_parser(
        "refresh",
        help="manually download a remote source into data/frozen, then optionally rebuild",
    )
    refresh.add_argument(
        "source_id",
        nargs="?",
        help="source id from config/sources.json; omit to refresh every snapshot source",
    )
    refresh.add_argument(
        "--build",
        action="store_true",
        help="run local ingest + rebuild after writing snapshots",
    )

    add_score = subparsers.add_parser(
        "add-score",
        help="append one manual observation and optionally rebuild",
    )
    add_score.add_argument("--benchmark", required=True, help="benchmark id, e.g. hle")
    add_score.add_argument("--model", required=True, help="public model name, e.g. GPT-5.6 Sol (max)")
    add_score.add_argument("--score", required=True, type=float, help="raw published score")
    add_score.add_argument("--url", required=True, help="public source URL")
    add_score.add_argument("--date", required=True, help="evaluation date YYYY-MM-DD")
    add_score.add_argument("--effort", default="", help="none/default/low/medium/high/xhigh/max")
    add_score.add_argument("--provider", default="", help="optional provider override")
    add_score.add_argument("--family", default="", help="optional family_id override")
    add_score.add_argument("--modality", default="", help="text/multimodal/vision/grid-visual")
    add_score.add_argument("--tier", default="benchmark_host", help="source tier")
    add_score.add_argument("--notes", default="", help="protocol or provenance note")
    add_score.add_argument("--build", action="store_true", help="rebuild after appending")

    subparsers.add_parser("validate-manual", help="validate manual observations CSV")
    subparsers.add_parser("doctor", help="inspect configuration and source state")
    return parser


def _validate_manual(root: Path) -> dict[str, object]:
    source = {
        "id": "manual_observations",
        "adapter": "manual_csv",
        "path": str(root / "data/manual/observations.csv"),
        "minimum_rows": 0,
    }
    aliases = AliasRegistry.from_csv(root / "data/manual/model_aliases.csv")
    adapter = ManualCsvAdapter(source, aliases)
    fetched = adapter.fetch()
    observations = adapter.parse(fetched)
    adapter.validate(observations)
    eligible = sum(item.is_eligible_native_no_tool() for item in observations)
    return {"rows": len(observations), "scoring_eligible": eligible}


def _load_sources(root: Path) -> dict:
    return json.loads((root / "config/sources.json").read_text(encoding="utf-8"))


def _refresh(root: Path, source_id: str | None) -> list[dict]:
    payload = _load_sources(root)
    sources = refreshable_sources(payload)
    if source_id:
        sources = [item for item in sources if item["id"] == source_id]
        if not sources:
            raise SystemExit(f"ksr: refreshable source not found: {source_id}")
    return [refresh_source(root, item) for item in sources]


def _add_score(root: Path, args: argparse.Namespace) -> dict[str, object]:
    config = load_index_config(root / "config/index.v1.json")
    spec = config.benchmarks.get(args.benchmark)
    if spec is None or spec.status != "active":
        raise SystemExit(f"ksr: unknown or inactive benchmark: {args.benchmark}")
    identity = public_model_identity(
        name=args.model,
        provider=args.provider,
        release_date=args.date,
        explicit_effort=args.effort,
    )
    if args.family:
        identity["family_id"] = args.family
    now = utc_now_iso()
    row = {
        "benchmark_id": spec.id,
        "benchmark_version": f"manual-{args.date}",
        "split": "default",
        "model_id": identity["model_id"],
        "family_id": identity["family_id"],
        "provider": identity["provider"],
        "display_name": identity["display_name"],
        "endpoint_date": identity["endpoint_date"] or args.date,
        "reasoning_effort": identity["reasoning_effort"],
        "tool_mode": "none",
        "modality": args.modality or "text",
        "raw_score": args.score,
        "metric": spec.metric_type,
        "ci_low": "",
        "ci_high": "",
        "sample_size": "",
        "source_id": "manual_observations",
        "source_url": args.url,
        "source_tier": args.tier,
        "eval_date": args.date,
        "retrieved_at": now,
        "protocol_hash": f"manual-{spec.id}",
        "raw_hash": "",
        "protocol_compatible": "true",
        "mutable_alias": "false",
        "notes": args.notes,
        "source_model_name": args.model,
        "input_cost_per_million": "",
        "output_cost_per_million": "",
        "speed_tokens_per_second": "",
        "context_window_tokens": "",
    }
    if spec.id == "arc_agi_2":
        row["modality"] = args.modality or "grid-visual"
    elif spec.id == "hle" and args.modality:
        row["modality"] = args.modality
    elif args.modality:
        row["modality"] = args.modality
    path = root / "data/manual/observations.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANUAL_FIELDS)
        if not existing or path.stat().st_size == 0:
            writer.writeheader()
        writer.writerow(row)
    return {
        "path": str(path.relative_to(root)),
        "family_id": row["family_id"],
        "benchmark_id": row["benchmark_id"],
        "raw_score": row["raw_score"],
        "reasoning_effort": row["reasoning_effort"],
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.root).resolve()
    try:
        if args.command == "update":
            manifest = run_pipeline(
                root,
                offline=args.offline,
            )
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
        elif args.command == "build":
            config = load_index_config(root / "config/index.v1.json")
            observations = load_observations(root / "data/state/observations.jsonl")
            source_state = read_json(root / "data/state/sources.json", {}) or {}
            manifest = build_artifacts(
                root,
                config,
                observations,
                source_state,
            )
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
        elif args.command == "refresh":
            reports = _refresh(root, args.source_id)
            payload: dict[str, object] = {"refreshed": reports}
            if args.build:
                payload["manifest"] = run_pipeline(root)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        elif args.command == "add-score":
            added = _add_score(root, args)
            payload = {"added": added}
            if args.build:
                payload["manifest"] = run_pipeline(root)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        elif args.command == "validate-manual":
            print(json.dumps(_validate_manual(root), ensure_ascii=False, indent=2))
        elif args.command == "doctor":
            config = load_index_config(root / "config/index.v1.json")
            payload = {
                "version": config.version,
                "config_warnings": config.validate(),
                "sources": read_json(root / "data/state/sources.json", {}),
                "manual": _validate_manual(root),
                "refreshable": [item["id"] for item in refreshable_sources(_load_sources(root))],
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
    except Exception as exc:  # CLI boundary; prints a concise actionable error.
        print(f"ksr: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
