---
name: research-frontier
description: 对已经检索到的文献题录做文献计量分析，识别热点、趋势、突现词与候选研究空白，并生成带方法说明和局限声明的报告。适用于用户要求分析研究趋势、找前沿方向、判断哪里还缺研究，且手上已有题录（标题/关键词/摘要/年份）时。不负责检索数据库——检索必须先用 research_papers 或 ars_resolvers 工具完成。
data_access_level: raw
task_type: multi-step
permitted_tools:
  - frontier_corpus_profile
  - frontier_hotspot_analysis
  - frontier_gap_analysis
  - frontier_report_build
---

# 研究空白与前沿探测（research-frontier）

## 适用场景

用户已经有一组文献题录（自己上传、或刚用检索工具拿到），并要求：

- 分析当前研究热点、趋势和前沿方向；
- 找出可能的研究空白，给出后续研究方向建议；
- 把这些分析整理成一份可读报告。

## 不适用场景

- 还没有题录：先调用 `mcp__research_papers__crossref_search` /
  `mcp__research_papers__europepmc_search` / `mcp__ars_resolvers__*` 检索，拿到题录后再用本技能。
- 用户要判断某篇论文的价值、真伪或结论对错：本技能不做这类判断，也不核验引用（用
  `frontier` 之外的核验/引用工具）。
- 语料只有几条：样本太小，结论不稳定，必须明确告知用户。

## 流程

1. **先检视语料**：把检索得到的题录写成 JSONL（每行一个对象，至少含 `title`，建议带 `year`、`keywords`、`doi`、`abstract`），用 `records_path` 传给 `frontier_corpus_profile`。看年份范围、缺失字段、重复 DOI，有警告先如实转述。
2. **热点与趋势**：`frontier_hotspot_analysis`。默认 `text_fields=["title","keywords"]`；
   有摘要时加 `"abstract"` 提高稳定性。`recent_years` 指语料中**最新**的 N 个年份，不是当前年份。
3. **研究空白**：`frontier_gap_analysis`。传入与主题相关的 `domain_terms` 和 `method_terms`；
   不传则用插件内置的通用词表，通用词表对本主题通常不够准确，应优先自己给词表。
4. **汇总报告**：`frontier_report_build`，把上面产出的 json 路径传进 `analysis_paths`。它同时返回 Markdown 正文，可直接用于回答，或作为 `latex_project_generate` 的 `material` 参数，不必再读文件。

每个工具都返回 JSON，包含 `artifacts`（绝对路径）。报告和表格以产物文件为准。

## 措辞要求（重要）

- 所有指标都是**文献计量代理指标**：它衡量的是“这组题录里有什么”，不是科学价值。
- 空白结论必须写成“在当前检索到的语料中，X 与 Y 的组合很少出现”，而不是“X 与 Y 是未被研究的方向”。
- 不得声称做过系统性综述，不得编造影响因子、引用次数或权威排名。
- 必须同时给出方法说明和局限，不能只给结论。
- 统计不显著不代表不存在，相关性也不代表因果。

## 产出

- 热点表：词、文献数、占比、趋势斜率、近期/基线速率、突现比。
- 空白表：领域 × 方法的观测数、期望数、残差，以及低文献量领域。
- 一份 Markdown 报告（含方法说明与局限）。
