# KSR Leaderboard

A public leaderboard for knowledge, science, and reasoning. Agent scores and coding are not included.

Live site: https://dideass.github.io/ksr-leaderboard/

| Benchmark | Weight | Source |
|---|---:|---|
| Humanity's Last Exam | 15% | [AA](https://artificialanalysis.ai/evaluations/humanitys-last-exam) |
| CritPt | 15% | [AA](https://artificialanalysis.ai/evaluations/critpt) |
| GPQA Diamond | 10% | [AA](https://artificialanalysis.ai/evaluations/gpqa-diamond) |
| MMLU-Pro | 10% | [Vals](https://www.vals.ai/benchmarks/mmlu_pro) |
| LiveBench Mathematics | 10% | [LiveBench](https://livebench.ai/) |
| LiveBench Reasoning | 10% | [LiveBench](https://livebench.ai/) |
| AA-Omniscience | 10% | [AA](https://artificialanalysis.ai/evaluations/omniscience) |
| ARC-AGI-2 | 10% | [ARC Prize](https://arcprize.org/leaderboard) |
| LiveBench Data Analysis | 5% | [LiveBench](https://livebench.ai/) |
| AA Long Context Reasoning | 5% | [AA](https://artificialanalysis.ai/evaluations/artificial-analysis-long-context-reasoning) |

```powershell
python -m pip install -e .
ksr update
ksr build
```

`ksr update` reads local snapshots only. Use `ksr refresh --build` to download new snapshots.
