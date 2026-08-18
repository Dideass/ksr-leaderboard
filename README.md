# KSR Leaderboard

Live site: https://dideass.github.io/ksr-leaderboard/

KSR (Knowledge, Science, Reasoning) ranks language models on those three things only.

## Design

Agent scores and coding do not measure a model's real intelligence. KSR keeps the tasks that are closer to talking through a scientific question with the model itself: facts, science, math, and novel reasoning, using each benchmark's native input and excluding known tool, search, and agent-harness runs.

One model appears once. A missing score stays blank — it is not a zero, a penalty, or a guess.

## Benchmarks

Weights are frozen and sum to 100%. No single board is above 15%.

**Humanity's Last Exam (15%)** — [AA](https://artificialanalysis.ai/evaluations/humanitys-last-exam). Expert-level questions across many fields. KSR uses the Artificial Analysis text-only catalog (2,158 questions, no tools).

**CritPt (15%)** — [AA](https://artificialanalysis.ai/evaluations/critpt). Research-grade physics. 70 challenges × 5 repeats; the model may write a function, but it has no code-execution tool.

**GPQA Diamond (10%)** — [AA](https://artificialanalysis.ai/evaluations/gpqa-diamond). Graduate-level science multiple choice. AA's 198-question Diamond set, 5× pass@1, no tools.

**MMLU-Pro (10%)** — [Vals](https://www.vals.ai/benchmarks/mmlu_pro). Broad academic knowledge. Vals.ai 5-shot chain-of-thought run of the official 10-option, 14-subject protocol.

**LiveBench Mathematics (10%)** — [LiveBench](https://livebench.ai/). Formal math on a dated, contamination-resistant set (AMPS Hard, integrals, contest math, olympiad).

**LiveBench Reasoning (10%)** — [LiveBench](https://livebench.ai/). Abstract and novel reasoning (theory of mind, zebra puzzles, spatial, logic with navigation).

**AA-Omniscience (10%)** — [AA](https://artificialanalysis.ai/evaluations/omniscience). Knowledge with a hallucination penalty: being wrong is worse than saying "I don't know."

**ARC-AGI-2 (10%)** — [ARC Prize](https://arcprize.org/leaderboard). Visual grid puzzles that test new-pattern reasoning. Official verified chain-of-thought, no tools; custom / synthesis / Kaggle systems are excluded.

**LiveBench Data Analysis (5%)** — [LiveBench](https://livebench.ai/). Tables and event sequences (joins, reformatting, consecutive events).

**AA Long Context Reasoning (5%)** — [AA](https://artificialanalysis.ai/evaluations/artificial-analysis-long-context-reasoning). Finding and combining evidence across a long context, no tools.

## Ranking

The ranking method is adapted from [AIHOT](https://aihot.virxact.com/leaderboard/rules): models only meet when both have a real score on the same benchmark; those pairwise outcomes are then fit into one global ability.

KSR keeps that idea, with frozen benchmark weights and a frozen set of anchor models so the scale stays comparable over time. Equal scores or overlapping published intervals count as a tie. The published KSR score is the model's average predicted win rate against the other anchors, not a weighted average of raw percentages.

A model gets an official rank only if it covers enough of the basket (at least 40% of the weight, 5 benchmarks, and both a knowledge/science board and a novel/synthesis board). Thin evidence still appears as a row, without a total.

## Build

```powershell
python -m pip install -e .
ksr update
ksr build
```

`ksr update` reads local snapshots only. Use `ksr refresh --build` to download new snapshots.
