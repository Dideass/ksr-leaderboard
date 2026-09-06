# September 6 leaderboard repair

Release: 3.6.1 (`bt-2026-09-06-published-rank-aa-lifecycle`).

## Findings and corrections

- **Missing AA scores:** the parser merged `deprecated` into `deleted`. Switching to the complete catalog exposed 345 deprecated endpoints, which were incorrectly excluded despite having published measurements. The two flags now remain separate in parsing and freezing. The snapshot was reconstructed from the complete September 5 catalog saved locally; no new benchmark download was performed.
- **Rank/score inversions:** ranks used latent ability while the displayed score used the average win probability against anchors, excluding an anchor's own comparison. Those orders can differ. The broken export contained two adjacent inversions. Ranks now follow public scores descending, with stable entity-ID tie breaking; the score formula and frozen anchors are unchanged.
- **Identity:** AA renamed HyperNova to include a reference to GPT-OSS. Name inference consequently assigned it to OpenAI. An explicit alias preserves Multiverse Computing and the existing model family.
- **Publishing:** a test assumed the ignored `work/` directory already existed. It now creates it. The workflow also checks the generated HTML against its JSON export, sequential ranks, score order, unique families, source health and per-benchmark coverage before uploading.

## Coverage reconciliation

Counts below are measured endpoint configurations, before one-row-per-family selection.

| AA benchmark | Broken release | Repaired |
| --- | ---: | ---: |
| HLE | 289 | 600 |
| GPQA Diamond | 290 | 609 |
| CritPt | 286 | 516 |
| AA-LCR | 250 | 447 |
| AA-Omniscience | 284 | 514 |
| GDP.pdf | 58 | 59 |
| Total | 1,457 | 2,745 |

The final site contains 456 families and 288 officially ranked models, versus 254 and 166 in the broken release. Its total observation count is 3,078.

All 494 slugs from the pre-migration AA snapshot are present in the recovered full catalog. Twenty older LCR measurements are absent from that catalog (both score and canonical token record are missing); those remain blank under the current protocol. Two endpoints changed display names (K-EXAONE 2.0 and HyperNova); their measurements are retained under their current names. Historical scores are not copied into missing current-protocol fields.

## Validation

- 53 unit tests pass, including deliberate anchor/non-anchor score inversions, deprecated versus deleted rows, offline per-field coverage failure, and complete-catalog freeze/parse round trips.
- The same 53 tests pass in a separate checkout-like directory without pre-existing `work/` or generated files.
- `python scripts/verify_site.py docs` validates all 456 HTML rows against JSON, with 288 sequential ranks and no score inversions. All four configured source states are healthy.
- Browser checks confirm restored Opus 4.8 scores, descending scores, pagination from 20 to 50 rows, HyperNova search/creator identity, model details, and no browser console errors.
- `git diff --check` passes. The generated `docs/` files are synchronized from the final build.

Future changes must follow `AGENTS.md` and `MAINTENANCE.md`. Never weaken coverage guards to make a large unexplained data loss pass validation.
