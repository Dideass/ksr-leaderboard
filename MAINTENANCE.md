# Maintaining KSR

Read `AGENTS.md`, `config/index.v1.json`, and `config/sources.json` first. The JSON manifests define the maintained basket and adapters. Historical commits are not instructions for the current project.

## Current basket and source contracts

Version 3.6.0, scoring revision `bt-2026-09-05-gdp-pdf-aa`, adopts professional document reasoning at 10%. Keep the existing anchors, effort-first family selection, and missing-score policy.

| Benchmark ID | Weight | Source | Contract |
| --- | --- | --- | --- |
| `hle` | 15% | AA | 2,158 text-only questions, no tools |
| `critpt` | 15% | AA | 70 research physics tasks × 5 repeats, no execution tool |
| `gpqa_diamond` | 10% | AA | 198 Diamond questions × 5 repeats, no tools |
| `gdp_pdf` | 10% | AA | All-pass, 100 tasks × 5 attempts, native document inputs, no tools |
| `aa_omniscience` | 10% | AA | Signed knowledge/hallucination index; existing floor-zero transform |
| `aa_lcr` | 5% | AA | v1.1, 100 questions × 3 repeats, no tools |
| `livebench_math` | 10% | LiveBench | Frozen 2026-06-25 task columns in source config |
| `livebench_reasoning` | 10% | LiveBench | Same frozen question-set version |
| `livebench_data_analysis` | 5% | LiveBench | Same frozen question-set version |
| `arc_agi_2` | 10% | ARC Prize | Verified CoT, semi-private 120 tasks; no custom/tool systems |

### GDP.pdf ingestion

The source is `https://artificialanalysis.ai/evaluations/gdp-pdf`. It exposes an initial chart selection and a public full-catalog manifest. `ksr refresh` follows that manifest with the same decoding used by the site's browser loader and freezes the normalized full catalog at `data/frozen/aa_measurements.json`. The decoder dependency is `cryptography`; no account credential is involved. The manifest asset path and key change over time and must be discovered from the page, never hardcoded.

The complete catalog also supplies the other five AA benchmarks. Each imported score requires its configured canonical token-count key. The current GDP.pdf field mapping is:

- Public score: `gdpPdfAllPass`, a proportion from 0 to 1.
- Frozen score and benchmark ID: `gdp_pdf`.
- Measurement provenance: `canonicalEvalTokenCounts.gdpPdf` (frozen as `canonical_eval_token_counts`).
- Input capability: `inputModalityImage` (frozen as `input_modality_image`). True means extracted text plus rendered page images; false means extracted text only.
- Metric: an attempt passes only if every atomic criterion passes. Use neither `macroCriterionPassRate` nor GDPval Elo. Do not mix AA and Surge implementations.
- Sample size metadata: 500 attempts, grouped within 100 tasks. `estimate_interval: false` avoids treating those attempts as independent. Leave unpublished intervals blank.
- Judge: GPT-5.6 Luna medium in the September 2026 AA protocol. Verify the upstream methodology on authorized refreshes; revise metadata and scoring revision if the actual protocol changes.

GDP.pdf belongs to `context_reasoning` and `novel_or_synthesis`, not the knowledge/science entry group. A model missing GDP.pdf keeps a blank; its 10% is neither transferred nor penalized.

## Full refresh

Only download when the user requests a source refresh. From the repository root:

```powershell
python -m pip install -e .
ksr refresh --build
ksr doctor
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
Copy-Item -Path artifacts/site/* -Destination docs -Recurse -Force
git diff --check
```

If the entry-point executable is not on PATH, use `$env:PYTHONPATH = 'src'` and `python -m ksr_index` in place of `ksr`. HTTP downloads respect the user's standard proxy environment; do not delete or hardcode their proxy settings.

Check these results before committing:

1. All three remote sources (LiveBench, AA, ARC) were downloaded. Every enabled source in `data/state/sources.json` has status `ok`, zero consecutive failures, and a recent check time. Ingest failures can retain old observations, so a successful process exit alone is insufficient.
2. Inspect GDP.pdf coverage and compare a few exact endpoint/effort values against AA, including the newest model. Full-catalog refresh enforces a minimum of 50 measured GDP.pdf configurations. Investigate any coverage drop; do not lower that guard simply to make a failing refresh pass.
3. Inspect new names across sources. Add identity overrides to `data/manual/model_aliases.csv` when inference would split one family or join distinct models. Never select a configuration because its score is higher.
4. Review `artifacts/data/manifest.json` and `ranking.json`: ten active benchmarks, total weight 100%, method ready, frozen anchors present, expected entry groups, no retired source rows. AA now supplies 65% of published benchmark weight; this concentration is deliberate.
5. Add a truthful release entry to `config/changelog.json`, then rebuild. A basket, protocol, or scoring change also requires an index version/scoring revision update. Ordinary fresh scores on the same protocol do not require changing anchors or weights.
6. Synchronize `docs/` from the final `artifacts/site/`, preserving `docs/.nojekyll`. Verify the new benchmark header, model detail score/source links, and release history in the generated page. Do not hand-edit generated HTML/JSON.

`ksr update` re-ingests local frozen files and prunes retired sources; `ksr build` only renders the saved observation store. After changing source or benchmark manifests, run `ksr update` or `ksr refresh --build` before relying on `ksr build`.

## Publishing

Commit the source/configuration changes, frozen snapshots, manual identity overrides, saved state, documentation, and synchronized `docs/` together. Keep temporary downloads and generated work outside the tracked tree. Do not rewrite Git history to clean a current release.

When the user requests a push, push the reviewed commit to the configured remote. A push to `main` triggers `.github/workflows/pages.yml`; the workflow tests and rebuilds offline from the committed state, then publishes `artifacts/site/`. Verify the workflow result and the live page's version before reporting deployment complete.
