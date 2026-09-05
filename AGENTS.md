# Agent notes

KSR is a static leaderboard. Scores come from frozen snapshots and a manual CSV. Do not fetch the public internet unless the user explicitly asks to refresh a source.

## Layout

- `config/index.v1.json` — ten-benchmark basket, weights, anchors, entry rules
- `config/sources.json` — ingest adapters and frozen snapshot paths
- `config/changelog.json` — homepage release history (newest first)
- `data/frozen/` — LiveBench, Artificial Analysis (six benchmarks), ARC
- `data/manual/observations.csv` — hand-added scores
- `data/manual/model_aliases.csv` — identity overrides
- `data/state/observations.jsonl` — merged observation store used by `ksr build`
- `src/ksr_index/` — ingest, identity, Bradley–Terry consensus, site
- `MAINTENANCE.md` — source contracts, full-refresh verification, and publishing checklist
- `docs/` — checked-in copy of the generated public site; sync from `artifacts/site/` after rebuilding
- `tests/` — run with `PYTHONPATH=src python -m unittest discover -s tests -v`

## Update paths

```powershell
python -m pip install -e .
ksr doctor
ksr refresh --build
ksr add-score --benchmark hle --model "Name" --score 12.3 --date YYYY-MM-DD --url URL --effort max --build
ksr build
```

`ksr update` and `ksr build` are offline. `ksr refresh` is the only command that downloads.

## Rules that must not drift

- One model family, one row. Selection order is effort, then source tier, then date. Never pick the higher score.
- Qwen `Max` is a product tier, not reasoning effort.
- Missing scores stay blank. No imputation, no penalty, no weight transfer.
- No active benchmark above 15%. Weights are multiples of 5% and sum to 100%.
- HLE uses only Artificial Analysis scores.
- GDP.pdf is active at 10%, ID `gdp_pdf`, dimension `context_reasoning`, entry group `novel_or_synthesis`. Use only AA's `gdpPdfAllPass` (normalized as `gdp_pdf`), requiring canonical token key `gdpPdf`. Never substitute criterion Mean Pass, GDPval, agent runs, or a different evaluator's result.
- GDP.pdf uses 100 tasks × 5 attempts, one turn, no browsing/tools. Record `multimodal` for image-capable endpoints and `text` for the rest. Do not invent confidence intervals from the 500 correlated attempts.
- The current basket revision is v3.6.0 / `bt-2026-09-05-gdp-pdf-aa`; the retired academic multiple-choice slot has been removed. Do not restore historical benchmark integrations from old commits or cached exports.
- AA refresh must follow the page-published full-catalog manifest (`full_catalog: true`). Initial chart models are only a subset. A failed full-catalog download must fail the refresh, not silently reuse a partial chart as fresh data.
- Preserve the frozen LiveBench question-set version during score refreshes. Moving to a new question set or changing an upstream evaluation protocol is a method revision.
- UI copy is English.

## After a method change

Bump `settings.scoring_revision` in `config/index.v1.json` and add a `config/changelog.json` entry. Rebuild, then run the test suite.

For every requested full refresh, follow `MAINTENANCE.md`: refresh all enabled remote sources, verify every source state is healthy, inspect family identities and per-benchmark coverage, synchronize `docs/`, and test before publishing. `doctor` prints state but is not proof that ingest succeeded; check for stale/failed sources explicitly. Do not claim a refresh succeeded when an upstream source failed.
