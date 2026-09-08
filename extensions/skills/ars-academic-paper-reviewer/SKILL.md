---
name: ars-academic-paper-reviewer
description: 学术论文评审：基于 Academic Research Skills 方法论的 5 席位多视角评审小组（期刊契合评审 + 3 名同行评审 + 魔鬼代言人），输出结构化编辑决定与修订路线图。只读，不修改稿件。触发词：审这篇论文、同行评审、模拟评审、评审、评审我写的稿子、review paper、peer review、editorial review、review my paper。
---

# 学术论文评审（ars-academic-paper-reviewer）

基于 Academic Research Skills（ARS）v3.21.2 的 `academic-paper-reviewer` Skill 适配。本平台上它作为 Hermes Agent Skill 存在：给出评审方法与输出契约，供 Agent 以多角色视角审阅论文，遵循项目约定不把教程中写出的用途视为已完成模块。

> 平台说明：上游 ARS 的 Claude Code 专有机制（slash 命令、subagent 分隔、`.claude/CLAUDE.md` 路由、校准流程）不在本平台生效。评审整体为**只读约束**：不得修改被审稿件；确需跨源核验引用时使用已接通工具。

## 适用场景

用户要求评审某篇论文（粘贴正文或提供文件）、模拟国际期刊评审、快速评估、按方法论聚焦或按审稿意见核验修订时使用。

## 运行流程

1. 自动识别论文所属领域与方法论类型，据此配置评审身份。
2. 以 5 个分离视角评审：期刊契合评审（选题与目标期刊匹配）、方法论评审、领域专家评审、跨学科视角、魔鬼代言人（挑战核心论点与逻辑谬误）。
3. 每项判断锚定具体标准与证据，按影响程度排列；不做总分到"接收 / 小修 / 大修 / 拒稿"的机械映射。
4. 跨源核验引用时按需调用 `mcp__ars_resolvers__openalex_verify`、`mcp__ars_resolvers__semantic_scholar_verify`、`mcp__ars_resolvers__arxiv_verify`、`mcp__ars_resolvers__chinese_literature_verify` 及 `mcp__research_papers__*`；只报告可观察结果，不复述模型记忆中的"已知事实"。
5. 由编辑综合器输出结构化编辑决定与修订路线图（重评审模式校验修订是否确实回应评审意见）。

## 失败与边界

核验工具降级时区分"数据源不可用"与"条目不存在"，不做猜测性匹配；未核实的内容不入评审结论。评审不验证稿件实际研究过程、原始数据真实性或结果可复现性——一致捏造可通过这些检查，需在报告中言明。

共享扩展不接触用户私有文献库；个人模型 Key 的隔离不等于 Skill / 文件沙箱隔离。