# Agent notes

KSR is a static leaderboard. Scores come from frozen snapshots and a manual CSV. Do not fetch the public internet unless the user explicitly asks to refresh a source.

## Layout

- `config/index.v1.json` — ten-benchmark basket, weights, anchors, entry rules
- `config/sources.json` — ingest adapters and frozen snapshot paths
- `config/changelog.json` — homepage release history (newest first)
- `data/frozen/` — LiveBench, AA, Vals, ARC, official HLE
- `data/manual/observations.csv` — hand-added scores
- `data/manual/model_aliases.csv` — identity overrides
- `data/state/observations.jsonl` — merged observation store used by `ksr build`
- `src/ksr_index/` — ingest, identity, Bradley–Terry consensus, site
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
- Official Scale HLE outranks AA only when effort is at least as high.
- UI copy is English.

## After a method change

Bump `settings.scoring_revision` in `config/index.v1.json` and add a `config/changelog.json` entry. Rebuild, then run the test suite.
