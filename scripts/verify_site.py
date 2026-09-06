"""Validate a built publication before upload (no network access)."""
from collections import Counter
from html.parser import HTMLParser
import json
from pathlib import Path
import sys


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.current = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr" and "model-row" in attrs.get("class", "").split():
            self.current = {"attrs": attrs, "rank": "", "score": ""}
            self.rows.append(self.current)
        if self.current and tag == "td":
            self.cell = {"rank-cell": "rank", "score-cell": "score"}.get(attrs.get("class"))
        if self.current and tag == "small":
            self.cell = None  # exclude the uncertainty from the displayed point

    def handle_endtag(self, tag):
        if tag == "td":
            self.cell = None
        if tag == "tr":
            self.current = None

    def handle_data(self, data):
        if self.current and self.cell:
            self.current[self.cell] += data


def verify(site):
    rows = json.loads((site / "data/ranking.json").read_text(encoding="utf-8"))
    manifest = json.loads((site / "data/manifest.json").read_text(encoding="utf-8"))
    assert manifest["leaderboard"]["method_ready"], "Method is not ready"
    assert all(s["status"] == "ok" for s in manifest["sources"].values()), "Unhealthy source"
    assert not manifest["config_warnings"], "Invalid basket configuration"
    assert len(rows) == len({r["entity_id"] for r in rows}), "Duplicate family"
    ranked = [r for r in rows if r["status"] == "ranked"]
    assert [r["rank"] for r in ranked] == list(range(1, len(ranked) + 1)), "Nonsequential ranks"
    assert [r["point"] for r in ranked] == sorted((r["point"] for r in ranked), reverse=True), "Score/rank inversion"
    assert manifest["leaderboard"]["ranked_count"] == len(ranked)
    assert manifest["leaderboard"]["row_count"] == len(rows)
    state = [json.loads(line) for line in Path("data/state/observations.jsonl").read_text(encoding="utf-8").splitlines()]
    counts = Counter((r["source_id"], r["benchmark_id"]) for r in state)
    config = json.loads(Path("config/sources.json").read_text(encoding="utf-8"))
    for source in config["sources"]:
        for benchmark, spec in source.get("score_fields", {}).items():
            assert counts[source["id"], benchmark] >= spec.get("minimum_models", 0), f"Lost {benchmark} coverage"
    parser = TableParser()
    parser.feed((site / "index.html").read_text(encoding="utf-8"))
    assert len(parser.rows) == len(rows), "HTML/JSON row count mismatch"
    for i, (html, row) in enumerate(zip(parser.rows, rows, strict=True)):
        attrs = html["attrs"]
        assert attrs["data-model-index"] == str(i)
        assert attrs["data-name"] == row["display_name"].lower()
        assert int(attrs["data-rank"]) == (row["rank"] or 99999)
        assert float(attrs["data-score"]) == (row["point"] if row["point"] is not None else -1)
        assert html["rank"].strip() == (f'{row["rank"]:02d}' if row["rank"] else "—")
        assert html["score"].strip() == (f'{row["point"]:.1f}' if row["point"] is not None else "—")
        assert row["observed_benchmarks"] == sum(c["observed"] for c in row["components"].values())
    print(f"Publication verified: {len(rows)} families, {len(ranked)} ranks; HTML and scores agree.")


if __name__ == "__main__":
    verify(Path(sys.argv[1] if len(sys.argv) > 1 else "artifacts/site"))
