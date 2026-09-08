---
name: ars-academic-pipeline
description: 学术全流程编排：基于 Academic Research Skills 方法论的 10 阶段流水线编排器，协调 ars-deep-research、ars-academic-paper、ars-academic-paper-reviewer，含完整性门、两阶段评审与过程记录。触发词：研究到论文、完整论文流程、全流程、research to paper、pipeline、end-to-end paper。
---

# 学术全流程编排（ars-academic-pipeline）

基于 Academic Research Skills（ARS）v3.21.2 的 `academic-pipeline` Skill 适配。本平台上它作为 Hermes Agent Skill 存在：它本身不做实质工作，只负责阶段检测、推荐模式、分派子技能、管理过渡与追踪状态，遵循项目约定不把教程中写出的用途视为已完成模块。

> 平台说明：上游 ARS 的 Claude Code 专有机制（slash 命令、subagent 编排、`model:` 微调、Model Tiering、Passport 复位边界流程）不在本平台生效。跨模型验证若需要，改接本工作站现有模型目录与个人 Key 路由（见 `docs/development/MODEL-SELECTION.md`），不复刻上游的 Claude 专有 tiering 语义。

## 适用场景

用户希望从研究主题一路做到成稿（阶段 1→6）、已有论文需要评审，或收到审稿意见需要修订时使用。每个阶段完成处需要用户确认检查点后才继续。

## 运行流程

1. **阶段检测与分派**：按用户输入判断从中途进入还是从头开始；把对应工作分派给 `ars-deep-research` / `ars-academic-paper` / `ars-academic-paper-reviewer`。
2. **RESEARCH（阶段 1）**：研究问题 + 方法学蓝图；采用 `ars-deep-research` 流程。
3. **WRITE（阶段 2）**：方法、论文写作、引用合规与双语摘要；采用 `ars-academic-paper` 流程。
4. **完整性门（阶段 2.5 + 4.5，强制）**：对引用存在性、声称-来源对齐、报告方法、图表保真与格式合规做确定性核验；依靠 `mcp__ars_resolvers__*` 与 `mcp__research_papers__*`，每次核验记录依据与采样；无记录跳过不允许。
5. **评审（阶段 3 / 3'）**：首次全量评审 + 修订后的聚焦核验评审；采用 `ars-academic-paper-reviewer` 流程；R&R 追溯矩阵独立校验作者修订声称。
6. **REVISE（阶段 4）**：按评审意见修订；区分可直接修正与需补实验；修订声称的强度变化需在路线图上有踪可查。
7. **FINALIZE（阶段 5）**：最终完整性门通过后格式化输出（APA 7.0 / Chicago / IEEE），PDF 编译依赖 tectonic。
8. **过程记录（阶段 6）**：产出论文创建过程记录与协作质量评估，作为交付物在最终确认前给出。

## 失败与边界

完整性门为强制项，覆盖范围有限、判定有真阳性上限；一致捏造可通过这些检查，需在报告中言明。共享扩展不接触用户私有文献库；个人模型 Key 的隔离不等于 Skill / 文件沙箱隔离。