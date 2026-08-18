from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import IndexConfig
from .models import ScoreRow


def short_name(value: Any) -> str:
    text = str(value or "")
    trimmed = re.sub(r"\s*\([^)]*\)\s*$", "", text).strip()
    return trimmed or text


def _load_changelog(root: Path) -> list[dict[str, Any]]:
    for path in (root / "config/changelog.json", Path("config/changelog.json")):
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return payload
    return []


def render_site(
    *,
    root: Path,
    config: IndexConfig,
    ranking_rows: list[ScoreRow],
    manifest: dict[str, Any],
) -> Path:
    package_dir = Path(__file__).parent
    output_dir = root / "artifacts/site"
    output_dir.mkdir(parents=True, exist_ok=True)
    environment = Environment(
        loader=FileSystemLoader(package_dir / "templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    environment.filters["percent"] = lambda value: f"{float(value) * 100:.0f}%"
    environment.filters["score"] = lambda value: "—" if value is None else f"{float(value):.1f}"
    environment.filters["short_name"] = short_name
    changelog = _load_changelog(root)
    template = environment.get_template("index.html.j2")
    html = template.render(
        config=config,
        version=config.version,
        ranking_rows=ranking_rows,
        benchmarks=[spec for spec in config.benchmarks.values()],
        manifest=manifest,
        sources=manifest.get("sources", {}),
        generated_at=manifest["generated_at"],
        active_benchmarks=config.active(),
        changelog=changelog,
        latest_update=changelog[0] if changelog else None,
    )
    (output_dir / "index.html").write_text(html, encoding="utf-8")
    for name in ("styles.css", "app.js"):
        shutil.copy2(package_dir / "static" / name, output_dir / name)
    data_dir = output_dir / "data"
    data_dir.mkdir(exist_ok=True)
    for obsolete in ("strict.json", "frontier.json", "chinese.json"):
        (data_dir / obsolete).unlink(missing_ok=True)
    for name in ("ranking.json", "manifest.json"):
        shutil.copy2(root / "artifacts/data" / name, data_dir / name)
    archive = shutil.make_archive(str(root / "artifacts/site"), "zip", output_dir)
    return Path(archive)
