# Academic Research Skills（ARS）适配接入计划

> 目标：把第三方仓库 `Imbad0202/academic-research-skills`（v3.21.2）的方法论资产接入本工作站。本计划只读遵循三个接入教程 [Skill](SKILL-INTEGRATION.md)、[MCP](MCP-INTEGRATION.md)、[插件](PLUGIN-INTEGRATION.md) 及 [README](../README.md) 的约定，规划 assets 的迁移、发布、验证与回退，不把教程里写出的用途当成已完成的模块。
>
> 核对日期：2026-09-08。适用版本：Hermes `693641aa…`、Open WebUI `0a7c1583…`（0.11.3）。

---

## 0. 目标与原则

- **接入目标**：将 ARS 的 4 个 Agent Skill（深度研究 / 论文写作 / 论文评审 / 全流水线编排）、其附属插件资产（slash 命令、hooks、agent 描述文件）、文献解析工具脚本与外部数据源调用能力，按 Hermes 层接入方式移植到本工作站的 `extensions/`，与现有 `paper-search` MCP、`research-citations` 插件、`research-literature` Skill 并存。
- **架构前提**（README §49、MCP 教程 §1）：链路是 浏览器 → Open WebUI → 工作站模型路由 → Hermes → 工具；工具与多轮规划在同一执行循环。`ws-*` 路由只转发消息白名单，不搬运 WebUI 工具执行循环。因此 **ARS 的所有执行端能力必须落在 Hermes / MCP / Skill 层**，WebUI 只做调用入口。
- **产出边界**：ARS v3.21.2 是 Claude Code 插件（plugin.json / slash 命令 / hooks / `.claude/CLAUDE.md`）。它的大部分"插件"机制（slash 命令解析、SessionStart announce hook、agent dispatch via slash）**不能原样搬到 Hermes**，需要拆解为 Hermes 可消费的 Skill、原生插件和 MCP 工具。本计划逐项给出映射与改造行动。
- **不被接纳的内容**：ARS 的 Bash 写作用域 guard、PreToolUse/PostToolUse hooks、subagent 编排依赖（Claude Code 私有的 SessionStart/SubagentStop 事件、`model:` 微调与 model tiering 的 Claude 专有语义）。这些在 Hermes 平台上没有对应契约，属"平台端口残差"，需要明确停用或重写，不能假装存在。

---

## 1. 资产盘点与映射总表

| ARS 资产 | 数量/示例 | 接入本平台的目标形态 | 对接教程 |
| --- | --- | --- | --- |
| 顶层 Skill（文档/SKILL.md） | 4：deep-research、academic-paper、academic-paper-reviewer、academic-pipeline | Hermes Agent Skill（`extensions/skills/<name>/SKILL.md`） | SKILL-INTEGRATION |
| Skill 的 references / shared 参考文件 | `references/`、`shared/*.md`（协议、schema、反模式） | Skill 的 `references/` 目录，正文按需链接 | SKILL-INTEGRATION §3 |
| `.claude-plugin/plugin.json` + skills 符号链接 | 套件元数据 | 转为 `extensions.json` 的 4 个 `skills` 条目 | SKILL-INTEGRATION §3 |
| slash 命令 `commands/ars-*.md`（16 个） | `/ars-plan`、`/ars-lit-review`、`/ars-full` 等 | **不直接当作命令**；改写成 Skill 内路由/触发条件和自然语言调用 | SKILL-INTEGRATION §5、PLUGIN §5 |
| `hooks/hooks.json` + announce/update-check | SessionStart announce、更新提醒 | 停用；无 Hermes 对应事件，避免误宣称"已搬运" | PLUGIN §6 |
| `agents/*_agent.md`（3 个插件级 agent） | synthesis/research-architect/report-compiler agents | 作为 Skill/references 中的子角色描述，或 Hermes 原生插件的 agent 角色 | PLUGIN §3、§6 |
| 文献解析脚本群 | `crossref_client.py`、`openalex_client.py`、`semantic_scholar_client.py`、`arxiv_client.py`、`chinese_literature_client.py` | **MCP 服务**（Hermes 直接连接 stdio）| MCP-INTEGRATION §1-3 |
| 确定性校验脚本群 | `verification_gate/`、`retraction_status.py`、`temporal_integrity_audit.py`、`citation_verification_summary.py` 等 | Hermes 原生插件注册为只读工具（`register(ctx)` / `ctx.register_tool`） | PLUGIN §2-4 |
| 内部脚本与 lint（`test_*.py`、`check_*.py`） | 数百个 CI 脚本 | **不进运行时**；仅作上游验收参考，本仓库改为 `tests/test_extensions.py` | 发布/回退流程 |
| 引用排版 | ARS 的 citation 处理（format-convert 模式） | 复用现有 `research-citations` 插件，避免重复实现 | PLUGIN §2 |

---

## 2. Skill 适配（第一批，独立、低风险）

### 2.1 新建目录与 frontmatter

按 SKILL 教程 §3，在 `extensions/skills/` 下新建 4 个目录，各自 `SKILL.md` 用本平台 frontmatter 规范重写：

```markdown
---
name: ars-deep-research
description: 深研究：13-agent 学术研究流程，8 模式……（写明触发条件，中英校验）
---
```

- **目录名与 `name` 相同、小写含连字符**。为避免与未来官方冲突，加 `ars-` 前缀（如 `ars-deep-research`），与现有 `research-literature` 并存。
- **白名单 `metadata.data_access_level` / `task_type` 保留**（ARS 自身用 `raw`/`open-ended` 枚举），因这些是 ARS 方法论契约，可映射到 Skill 的 frontmatter 注释。
- 4 个技能之间的 `related_skills` / `depends_on` 保留为文档级链接，不在 Hermes 层级强制解析。

### 2.2 拦下 Claude Code 专有机制

- **忽略** `.claude/CLAUDE.md` 的 routing discipline、意图澄清、phase boundary 判定中的 Bash 依赖。改写成 Skill 正文里的"适用场景 / 触发条件 / 非触发场景"引导。
- **slash 命令不搬运**：ARS 的 16 个 `/ars-*` 命令在 Hermes API 接入下不可解析（SKILL 教程 §5）。把它们改写成每个 Skill 的 `### 触发关键词`（中英）和自然语言调用示例，例如 `/ars-plan` → "引导我规划论文结构"。
- **agent 编排**：ARS 的 subagent orchestration 依赖 Claude Code 的脚手架。本平台把每个 agent 角色写为 Skill 内流程角色或 references 说明，不复制子代理运行时。

### 2.3 依赖的真实工具

Skill 只描述方法，真正访问数据依赖已接通工具（SKILL 教程 §1）。ARS 四个技能凡出现检索/核验步骤，正文必须引用本平台实际工具名，例如：

- 元数据检索：`mcp__research_papers__crossref_search` / `europepmc_search`
- DOI 核验：`mcp__research_papers__crossref_lookup`
- 开放正文：`mcp__research_papers__europepmc_fulltext`
- 引用排版：`research_citation`
- 新增解析工具（§4）：`mcp__ars_resolvers__openalex_search` 等

**绑定关系**：ARS 的 `deep-research`（文献综述）复用现有 `research-literature` 的 MCP 证据层级约定（元数据/摘要/全文片段）；`academic-paper` 的 citation-check / format-convert 模式调用 `research_citation` 插件；`academic-paper-reviewer` / `academic-pipeline` 的完整性门（Stage 2.5/4.5）可选用 §4 的解析与校验工具。正文不得出现 Skill 中不存在的工具名（SKILL 教程 §3）。

### 2.4 配置清单登记

在 `configs/workstation/extensions.json` 的 `skills` 数组追加 4 个名字，保留 `research-literature`：

```json
"skills": ["research-literature", "ars-deep-research", "ars-academic-paper",
           "ars-academic-paper-reviewer", "ars-academic-pipeline"]
```

在 `api_toolsets` 保留 `skills`（使 `skills_list` / `skill_view` / `tool_search` 可用）。

---

## 3. 插件适配（Hermes 原生插件）

### 3.1 适合作为插件的能力

ARS 的**确定性校验脚本**（无网络或已封装网络、只读、纯 Python）映射为 Hermes 原生插件，用 `register(ctx)` + `ctx.register_tool` 暴露（PLUGIN 教程 §3）。候选清单：

| 插件名（建议） | 暴露工具 | 来自 ARS 的脚本 | 说明 |
| --- | --- | --- | --- |
| `ars-verification` | `ars_verify_citation` | verification_gate 封装 | 四索引引用存在性核验，输出 `lookup_verified` 三态 |
| `ars-retraction` | `ars_check_retraction` | `retraction_status.py` | 只读解析已获取元数据，判定 retracted/reinstated |
| `ars-temporal` | `ars_temporal_integrity` | `temporal_integrity_audit.py` | 时间一致性 5 道检查 |

每个插件目录 `extensions/plugins/<name>/` 含 `plugin.yaml` + `__init__.py`：

```yaml
name: ars-verification
version: "0.1.0"
description: Verify cited references against bibliographic indexes without inventing results.
provides_tools:
  - ars_verify_citation
```

```python
def handle_verify(params, **kwargs):
    # 校验参数、调用 verification_gate、如实返回 lookup_verified=true/false/unresolvable
    ...

def register(ctx):
    ctx.register_tool(name="ars_verify_citation", toolset="ars_verification",
                      schema={...}, handler=handle_verify)
```

约定（PLUGIN 教程 §3）：工具名/插件名/工具集名不覆盖现有 `research_citations` & `research_citation`；`description` 给模型看真实边界；错误与超时在实现里处理，不依赖模型传参正确；`**kwargs` 保留兼容。

### 3.2 明确停用的插件资产

- **不搬运**：`hooks/hooks.json`（SessionStart announce、update-check）——Hermes 没有对应启动事件，**不得**宣称"启动时已注入命令清单"。
- **不搬运**：写作用域 guard（`ars_write_scope_guard.py` + `run_guard.sh`）——Bash + PreToolUse 是 Claude Code 私有契约，本平台无等效沙箱；接受降级为"不激活"，文档注明。
- **不搬运**：model tiering / 跨模型验证的 Claude agent 分派语义；如确有跨模型需求，改接现有模型路由与个人 Key 体系（见 MODE-SELECTION 说明，README §57），而非复制 ARS 的 tiering 语法。

### 3.3 配置登记

把插件名加入 `extensions.json` 的 `plugins` 数组，工具集名加入 `api_toolsets`；部署器据此写入 Hermes `config.yaml` 的 `plugins.enabled` 与 `platform_toolsets.api_server`（PLUGIN 教程 §4）。保留 `research-citations` 和 `research_citations` 条目。

---

## 4. MCP 工具适配（文献解析数据源）

### 4.1 新增 stdio MCP 服务

现有 `extensions/mcp/paper-search/server.py` 已封装 Crossref + Europe PMC。ARS 独有的解析器需要补充：**OpenAlex**、**Semantic Scholar**、**arXiv**、**中国文献解析器**。建议新建 `extensions/mcp/ars-resolvers/server.py`（官方 MCP Python SDK），复用 ARS 的 `openalex_client.py` / `semantic_scholar_client.py` / `arxiv_client.py` / `chinese_literature_client.py` 的查询与降级逻辑，包装为业务工具（MCP 教程 §3 最小服务骨架）。

| Hermes 实际工具名（预期） | 数据源 | 说明 |
| --- | --- | --- |
| `mcp__ars_resolvers__openalex_search` | OpenAlex | 题名精确阈值 + 通用标题降级（复用 ARS 的 #431 exact-title-or-bust 门）|
| `mcp__ars_resolvers__semantic_scholar_lookup` | Semantic Scholar | 1 req/s 节流，S2_API_KEY 可选 |
| `mcp__ars_resolvers__arxiv_lookup` | arXiv | arXiv-ID-first + 题名交叉核对，遵循 ToU 3s 节奏 |
| `mcp__ars_resolvers__chinese_literature_search` | 中文文献源 | 复用 ARS 的解析客户端与失败降级 |

> **双下划线命名**：以当前运行源码实测为准，不凭字符串惯例推断（MCP 教程 §2）。以上名称为预期，需在 Hermes 发现完成后以实际注册名为准。

### 4.2 配置模板（占位符由部署器展开）

```yaml
mcp_servers:
  ars_resolvers:
    command: /home/ubuntu/haudi-hermes/venv/bin/python
    args:
      - /home/ubuntu/haudi-hermes/extensions/releases/<release-id>/mcp/ars-resolvers/server.py
    enabled: true
    timeout: 60
    connect_timeout: 30
    supports_parallel_tool_calls: false
    tools:
      include: [openalex_search, semantic_scholar_lookup, arxiv_lookup, chinese_literature_search]
      resources: false
      prompts: false
```

`platform_toolsets.api_server` 追加 `ars_resolvers`（这是 MCP 服务名）。`extensions.json` 的 `mcp_servers` 增加同名段落，并把服务名加入 `api_toolsets`。

### 4.3 失败与边界契约

- 沿用 ARS 降级语义：单个解析器网络故障只标记该数据源 `*Unavailable` / `unresolvable`，**不**整条中止（与 `paper-search` 的 429/5xx 重试约定一致）。
- 校验工具（§3）依赖这些解析器时，通过 MCP 工具在 Hermes 执行循环内调用；ARS 内部脚本的"直接 import scripts.X"路径在 Hermes 插件/MCP 中被隔离，改写为函数级引用，避免跨层 import 破坏类身份。
- SQLite 缓存（ARS 的 `verification.db`、retraction cache）若要保留，写入服务器 `state/` 下并设置 TTL，不让检索词泄漏进日志；按研究资料管理（MCP 教程 §6）。密钥/凭据只走 `state/.env`（权限 600），仓库只留变量引用。

---

## 5. 工具（脚本）层的处理策略

ARS 的 `scripts/`（数百个 `check_*`、`test_*`、迁移脚本）**不属于运行时扩展**：

- **不进发布包**：`package_extensions.py` 只打包扩展源码/配置/依赖清单和部署脚本（MCP 教程 §4），不要把这些 lint 拉进 `extensions.zip`。
- **验收价值**：把与本平台相关的确定性校验逻辑抽成 1 个统一入口，供 `verify-extensions.py` 调用（验证 Skill 加载 + MCP 实际调用 + 插件工具注册），而不是维护 ARS 全部 CI。
- **测试对齐**：本仓库业务测试加到 `tests/test_extensions.py`，覆盖：Skill 能经 `skill_view` 加载且 frontmatter 合法、4 个 CRUD-based resolver 的真实调用、新插件工具的注册与错误返回、`connection 失败`与边界（PLUGIN 教程 §5）。

---

## 6. 发布、验证与回退（统一步骤）

复用三类扩展共用流程（SKILL/MCP/PLUGIN 教程：本地仓库根目录 PowerShell）：

```powershell
python -m unittest discover -s tests -p test_extensions.py -v
python scripts/package_extensions.py
python deploy/hermes/upload.py .build/extensions.zip /home/ubuntu/haudi-hermes/extensions.zip
python deploy/hermes/upload.py deploy/hermes/deploy-extensions.py /home/ubuntu/haudi-hermes/deploy-extensions.py
python deploy/hermes/remote.py deploy/hermes/deploy-extensions.sh
```

- **发布顺序建议**：先 MCP 解析服务（§4）→ 再插件（§3）→ 后 Skill（§2），因为它们有依赖（Skill 引用已接通的工具）。每步独立校验后再进行下一步，若失败可单步回退。
- **服务端验证**（不调用 LLM）：
  ```bash
  python deploy/hermes/remote.py deploy/hermes/verify-extensions.sh   # 或服务器上重跑当前 release 的 verify-extensions.py
  curl --fail http://127.0.0.1:8642/health
  cat /home/ubuntu/haudi-hermes/extensions/verification.json          # 记录真实工具调用结果
  ```
- **网页端验收**：选择已配置个人 Key 的模型新建任务，例如：
  > 加载 ars-deep-research 技能，检索两篇开放论文并用 europepmc_fulltext 读取正文片段，列出 DOI、来源与证据层级。
  验收必须确认模型**实际执行了工具调用**，而不只看它声称已检索（MCP 教程 §4、SKILL 教程 §5）。
- **回退**：读取 `extensions/deployment.json` 的 `backup` 路径，跑 `venv/bin/python deploy-extensions.py --rollback "$backup"`；回退保留共享环境新增依赖包，恢复配置与 Skill/插件目录（MCP 教程 §6）。手动回退后以当前 `state/config.yaml` 核实状态，不误信 `deployment.json` 仍是"最新"。
- **停用单个 Skill**：从 `extensions.json` 的 `skills` 移除并把服务器对应目录移出 `state/skills` 后重启；发布器不做自动清理（SKILL 教程 §7）。

---

## 7. 多用户与凭据边界（必读限制）

- ARS 的插件与 MCP 在本平台是**共享执行环境**（SKILL 教程 §7、MCP 教程 §5）。个人模型 Key 隔离不等于 Skill / 文件沙箱隔离。
- 若未来接入私有 Zotero / 机构文献库，须先实现用户身份传递、服务端权限检查与凭据隔离；**不能**把 ARS 现有的共享解析器直接绑私有凭证。
- 本计划新增的 MCP（OpenAlex/S2/arXiv/中文源）**不要求 API Key**（S2 可选），与现有 `paper-search` 一致；查询词会发送给相应论文服务，按研究资料管理。

---

## 8. 工作项清单（按依赖排序）

1. **分析冻结**：逐 skill 抽取被 ARS 引入的网络/外部工具引用，产出"Skill 步骤 ↔ 本平台工具"映射表（2.3）。
2. **MCP 解析服务**：新建 `extensions/mcp/ars-resolvers/`，移植 4 个解析客户端，写单元测试 + 端到端调用测试。
3. **解析/校验插件**：新建 `ars-verification`、`ars-retraction`、`ars-temporal` 三个插件，注册只读工具。
4. **Skill 移植**：写 4 个 `SKILL.md`，重写 frontmatter、触发条件、工具引用，剥离 Claude Code 专有机制。
5. **配置合并**：更新 `configs/workstation/extensions.json`（skills/plugins/mcp_servers/api_toolsets），合并 Hermes 目标 config 片段。
6. **依赖固定**：新增所需 Python 包写进 `requirements.txt`，服务器 `existing-packages.txt` 记录既有版本，升级冲突时停止（MCP 教程 §3）。
7. **测试与验收**：扩展 `tests/test_extensions.py` + 更新 `verify-extensions.py` 预期（Skill 加载、MCP 实调、插件注册）。
8. **发布与回退演练**：按 §6 执行，保存 release/backup 记录，验证回退路径。

---

## 9. 交付检查（对齐 PLUGIN 教程 §7）

交付 ARS 接入时附：
- 每个组件的源码、清单、依赖变更与真实调用验收记录；
- 明确它运行在 Hermes 层还是 WebUI（本计划全部为 Hermes 层）；
- 是否读写外部系统（MCP 读外部 API；校验插件只读解析已获取数据）；
- 使用哪些凭据（无额外 Key，S2 可选）、是否共享数据（共享执行环境，日志含检索词）。
- 凭据、日志、服务器备份与账号库不进 Git。若改上游源码，按项目补丁流程走 `patches/`，不直接复制进 `reference/`。