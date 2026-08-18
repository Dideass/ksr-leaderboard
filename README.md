# KSR Index

KSR（Knowledge and Scientific Reasoning Index）是一个只衡量知识、科学与推理能力的公开证据排行榜。项目现在只生成一张总榜：每个明确模型世代出现一次，点击模型即可检查全部 benchmark 分数、缺测、推理强度、输入模态、版本和来源。

v3.4 的协议不再强制“纯文本”。它采用 benchmark 的原生输入模态（文本、图文或网格视觉），同时排除浏览、搜索、Python／计算器、agent harness、程序搜索及其他外部工具。HLE 官方 Scale 总榜没有单列工具开关；AA 的 HLE 为独立 text-only 评测。KSR 将二者都作为 direct-model 协议接纳，并在每项详情中保留来源与协议备注。AA 公布的 Fallback／composite 端点按该模型计入，并在备注中标明。页面为英文。

排行榜**不会每天自动抓取**。分数来自仓库内冻结快照和手工观测；需要更新时由人或 agent 显式刷新快照、追加分数，再本地重建。

## 当前计分篮子

| 能力问题 | Benchmark | 权重 | 点击跳转 |
|---|---|---:|---|
| 学术与专业知识 | Humanity's Last Exam | 15% | [AA](https://artificialanalysis.ai/evaluations/humanitys-last-exam) |
| 高难科学推理 | GPQA Diamond（AA 5× pass@1） | 10% | [AA](https://artificialanalysis.ai/evaluations/gpqa-diamond) |
| 综合学术知识 | MMLU-Pro（Vals 5-shot CoT） | 10% | [Vals](https://www.vals.ai/benchmarks/mmlu_pro) |
| 研究级物理推理 | CritPt（70 challenges × 5，无代码执行） | 15% | [AA](https://artificialanalysis.ai/evaluations/critpt) |
| 数学与形式推理 | LiveBench Mathematics 2026-06-25 | 10% | [LiveBench](https://livebench.ai/) |
| 抽象推理与新题迁移 | LiveBench Reasoning 2026-06-25 | 10% | [LiveBench](https://livebench.ai/) |
| 数据与表格推理 | LiveBench Data Analysis 2026-06-25 | 5% | [LiveBench](https://livebench.ai/) |
| 长上下文综合 | Artificial Analysis LCR | 5% | [AA](https://artificialanalysis.ai/evaluations/artificial-analysis-long-context-reasoning) |
| 认识论可靠性 | AA-Omniscience | 10% | [AA](https://artificialanalysis.ai/evaluations/omniscience) |
| 抽象网格迁移 | ARC-AGI-2 verified CoT | 10% | [ARC Prize](https://arcprize.org/leaderboard) |

总权重固定为 100%，各项均为 5% 的倍数，单项不超过 15%。MMLU-Pro 使用 [Vals.ai](https://www.vals.ai/benchmarks/mmlu_pro) 的 5-shot CoT 独立评测。Artificial Analysis 承载的 CritPt、LCR 与 Omniscience 合计 30%。ARC-AGI-2 从官方 `v2.json` 导入全部 verified CoT。置信度按评测完整度标注：覆盖率 ≥80% 且至少 7 项为 High；≥50% 为 Medium。

HLE 的计分优先级：官方 Scale `finalized-2500` 多模态总榜（`benchmark_host`）高于 AA 2,158 题 text-only 独立评测（`independent`）。同一模型两处都有分时取官方；AA 只补官方未测的模型。页面上的 HLE 卡片指向覆盖最完整的 AA 评测页。

按既有要求，FACTS Parametric、FACTS Grounding v2、FrontierScience Olympiad／Research、MathArena、SciPredict、CL-bench 以及中文榜均已从活动配置移除。历史原始文件与旧快照只为审计保留，不影响现榜。

## 数据覆盖

- LiveBench 使用官网 `https://livebench.ai/table_2026_06_25.csv` 的冻结快照（当前 43 个配置），不再使用 GitHub Pages 上较旧的 28 行表。
- HLE 同时保留官方 Scale 标准总榜与 AA 独立评测；AA 目录中带 canonical token counts 的 HLE 成绩全部计入，包括官方公布的 Fallback 端点（例如 Claude Fable 5）。
- GPQA、CritPt、LCR、Omniscience 来自 AA 公开 catalog 冻结快照，并要求存在 canonical token-count。
- MMLU-Pro 来自 Vals.ai 公开榜（当前 133 个模型）的冻结快照。
- Qwen 的 `Max` 是产品档位，不会再被误识别成推理强度，从而把 AA 与 LiveBench 拆成两个实体。
- ARC-AGI-2 从官方 [leaderboard v2.json](https://arcprize.org/media/data/leaderboard/v2.json) 导入全部 verified CoT（当前约 180 行），不再手工摘抄。Custom / synthesis / Kaggle 仍排除。

冻结快照位于 `data/frozen/`。官方 HLE 标准总榜在 `data/frozen/hle_standard_official.csv`。本地审计草稿在 `work/`，不进入公开仓库。

## 排名方法

### 一个模型只出现一次

实体键是“提供商＋明确型号世代”。Pro、mini、Preview、Codex 等明确产品不会被合并；日期化 endpoint 和推理档位属于配置，不会被错误拆成新模型。

同一实体在同一 benchmark 有多个成绩时，选择过程不看分数，只按预注册顺序：

1. `max > xhigh > high > medium > low > default > none`；
2. benchmark 官方榜单 > 独立统一评测 > benchmark 作者 > 厂商自报；
3. 同档同来源取最新 dated endpoint。

### 固定证据预算与共同参评

KSR 参考 AIHot 的“共同参评→成对结果→全局能力”思路，但使用冻结 benchmark 权重与冻结锚点来保持时间可比性。对于某一 benchmark，只有同时拥有有效成绩的两款模型才产生胜、负或平局；原始分相同或公开置信区间重叠时记平局。

每项 benchmark 的固定预算在其实际参评模型间分配：

```text
单场证据权重 = 84 × benchmark 固定权重 ÷（该 benchmark 入榜圈参评数 − 1）
```

全部加权成对结果用带零中心弱先验的 Bradley–Terry 模型联合估计。页面显示的 KSR 共识分是模型相对冻结锚点的平均预测胜率：

```text
KSR Score = 100 × mean(sigmoid(模型能力 − 其他冻结锚点能力))
```

因此它不是把不同 benchmark 的原始百分比直接相加，也不会因某个榜单突然多出大量模型而扩大该榜权重。

### 缺测不等于失败

缺测不补 0、不补 50、不补均值、不做模型预测，也不把空缺权重转给其他 benchmark。缺测只会减少真实共同参评、提高标准误并降低置信度。

正式名次要求：固定权重覆盖率至少 40%，至少 5 个 benchmark、3 个能力维度，同时具备一项知识／科学证据和一项新题／综合证据，并与至少 2 个冻结锚点直接共同参评。不满足门槛的模型仍只显示一行及逐项画像，但不制造总分。相邻模型的 95% 区间重叠时仍保留严格排序，页面会明确提示该顺序不代表差异显著。

## 运行与手工更新

需要 Python 3.12 或更高版本：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
ksr doctor
ksr update
```

`ksr update` **只读本地冻结快照和手工 CSV，不访问网络**。只用已有观测重新计算：

```powershell
ksr build
```

### 给 agent：加入新模型或刷新榜单

按改动类型选一条路径即可。

**1. 官方源上已经出现新模型（LiveBench / AA / Vals）**

```powershell
ksr refresh livebench_release --build
ksr refresh aa_public_measurements --build
ksr refresh vals_mmlu_pro --build
ksr refresh arc_agi_2_verified_cot --build
# 或一次刷新全部可快照源：
ksr refresh --build
```

`refresh` 会覆盖 `data/frozen/` 中对应文件，然后本地重算。LiveBench 新模型名一般能从 `gpt-5.6-sol-max` 这类后缀推断身份；推断不准时在 `data/manual/model_aliases.csv` 加一行即可。

**2. 只给某一个模型补一条公开分数**

```powershell
ksr add-score --benchmark hle --model "GPT-5.6 Sol (max)" --score 49.49 --date 2026-08-18 --url "https://artificialanalysis.ai/evaluations/humanitys-last-exam" --effort max --build
```

分数写入 `data/manual/observations.csv`。同一模型同一榜已有更高推理档或更高权威来源时，手工分不会覆盖选行规则。

**3. 批量手工分**

直接编辑 `data/manual/observations.csv`（表头已在文件中），必要时补 `data/manual/model_aliases.csv`，然后：

```powershell
ksr validate-manual
ksr update
```

`ksr doctor` 可查看配置、各源状态和可 refresh 的源 id。

## 发布到 GitHub Pages

仓库已带 `.github/workflows/pages.yml`。把 `main` 推到 GitHub 后：

1. 打开仓库 **Settings → Pages**
2. **Source** 选 **GitHub Actions**
3. 等名为 `Deploy site` 的 workflow 跑完

站点地址是 `https://<user>.github.io/ksr-leaderboard/`。也可以用 **Settings → Pages → Deploy from a branch**，文件夹选 `/docs`（仓库里预置了当前静态页）。

主要输出：

- `artifacts/site/index.html`：可搜索、筛选、排序并展开逐项详情的单榜页面；
- `artifacts/site.zip`：完整静态站点；
- `artifacts/data/ranking.csv` 与 `ranking.json`；
- `artifacts/data/observations.parquet`；
- `artifacts/data/manifest.json`：方法、来源状态、哈希、锚点、覆盖和饱和监控。

来源适配器位于 `src/ksr_index/adapters/`。未变化的冻结快照复用已验证内容哈希；单源失败保留 `latest_good` 并标记 stale。当前测试覆盖机会校正、最高推理强度、模型唯一性、原生多模态协议、缺测保持空白、固定权重、来源冲突、AA 公开 payload、快照幂等和页面单榜结构。
