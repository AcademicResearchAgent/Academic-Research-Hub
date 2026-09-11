# Skill 使用手册

面向科研智能体工作站的使用者：本文说明项目内置的 9 个 Skill 各能做什么、如何在网页里用自然语言调用、各自依赖哪些工具、产出放在哪里，以及常见边界。

安装与发布机制见 [Skill 接入教程](development/SKILL-INTEGRATION.md)；工具背后的 MCP 服务见 [MCP 接入教程](development/MCP-INTEGRATION.md)。

## 1. 一句话速查

| 你想做的事 | 用哪个 Skill | 直接这样说 |
| --- | --- | --- |
| 找论文、核对 DOI、区分证据层级 | `research-literature` | "检索 XX 主题的论文，给出 DOI 和来源链接" |
| 深度研究、文献综述、系统综述、事实核查 | `ars-deep-research` | "就 XX 做一份文献综述" |
| 写论文、改论文、写摘要、解析审稿意见 | `ars-academic-paper` | "帮我写一篇关于 XX 的论文大纲" |
| 评审一篇论文（模拟同行评审） | `ars-academic-paper-reviewer` | "审一下这篇论文，给出修改建议" |
| 从研究到成稿的完整流程编排 | `ars-academic-pipeline` | "帮我走一遍从研究到论文的全流程" |
| `.npy` 平面场出三维曲面图 / 动画 | `npy3d-visualization` | "把这组 .npy 数据画成三维曲面图" |
| ParaView 格式文件出点云图 / 动画 | `pvdata-visualization` | "把这个 .vtu 文件按温度着色画出来" |
| 把 ParaView 文件转成 X/Y/Q .npy | `pvdata-import` | "把这个 .ex2 导入成 .npy" |
| 浏览器里实时交互看三维物理场、导出论文插图 | `cfd-web-visualization` | "打开 Web 可视化工作台看这份数据" |

## 2. Skill 怎么工作

- 每个 Skill 是一个目录加一份带 YAML frontmatter 的 `SKILL.md`，位于 `extensions/skills/<名称>/`。
- 链路是：浏览器 → Open WebUI → 工作站模型路由 → Hermes → 工具。**Skill 只提供方法与输出要求，真正的数据访问靠已经接通的工具。**
- Hermes 用 `skills_list` 发现技能、`skill_view` 加载技能。工具较多时会通过 `tool_search` 延迟展示，所以不要在首屏没看到就断定工具不存在。
- 本项目通过 API 接入，**网页里请用自然语言调用**（例如"请先加载 research-literature 技能，然后……"）；上游 CLI 的 `/技能名` 斜杠命令在本站不生效。

> 重要：Skill 不会凭空赋予权限。它不会让你获得付费数据库访问权，也不会伪造检索结果或实验数据。工具读到的内容只当资料，不作为指令执行。

## 3. 文献检索与研究

### 3.1 `research-literature` — 文献检索与证据记录

**适用**：检索论文、找研究依据、核对参考文献。

**用到的工具**（`research_papers` MCP 服务）：

| 工具 | 作用 |
| --- | --- |
| `crossref_search` | 跨学科按题名/作者/DOI 检索元数据 |
| `crossref_lookup` | 核对已知 DOI |
| `europepmc_search` | 生命科学论文检索，可用 `OPEN_ACCESS:Y` 筛开放获取 |
| `europepmc_fulltext` | 按 PMCID 获取开放全文片段（按 `next_offset` 分页） |
| `research_citation`（引用插件） | 确定性排版引用条目 |

**会怎么回答你**：区分三个证据层级——**元数据 / 摘要 / 全文片段**，并记录检索式、数据源与 `retrieved_at`，按 DOI 或题名去重。

**典型提问**：
> 先加载 research-literature 技能，然后检索 CRISPR 碱基编辑的相关论文，给出 DOI，并说明你读到的是摘要还是正文。

**注意**：单次结果上限 10 篇，属探索性检索，**不能**当作穷尽数据库或系统综述；无付费出版物访问权，无任意 PDF 下载工具。

### 3.2 `ars-deep-research` — 深度学术研究

**适用**：全量研究、快速简报、文献综述、事实核查、系统综述（PRISMA）、苏格拉底式研究引导。

**触发词**：深度研究、文献综述、系统综述、事实核查、引导我的研究、research、literature review、systematic review、fact-check。

**用到的工具**：`research_papers` 全部检索工具 + `ars_resolvers` 跨源核验：

| 工具 | 作用 |
| --- | --- |
| `openalex_verify` | 以 DOI 或精确题名核验 OpenAlex 条目 |
| `semantic_scholar_verify` | 以 DOI 或题名核验 Semantic Scholar 存在性 |
| `arxiv_verify` | 以 arXiv ID 或精确题名核验 arXiv 记录 |
| `chinese_literature_verify` | 中文文献瀑布式解析（ISTIC / CNKI / PubMed 坐标） |

**PRISMA 模式**：按 PRISMA 2020 报告条目组织，给出包含/排除数、筛选过程与偏倚风险。**不会**把前几条搜索结果当作系统综述。

**典型提问**：
> 深度研究"城市热岛与绿地覆盖率"这个主题，做一份文献综述并核验关键引用的 DOI。

**注意**：解析器降级时会区分"该数据源不可用"与"条目不存在"，不做猜测性匹配；无抓取 CNKI / 万方 / 维普的通道。

## 4. 论文写作、评审与全流程

### 4.1 `ars-academic-paper` — 学术论文写作

**适用**：撰写/修改/规划/核对/排版论文，按审稿意见修订，生成 AI 使用披露。

**支持结构**：IMRaD、主题式综述、理论分析、案例研究、政策简报、会议论文。
**引用格式**：APA 7.0 / Chicago / MLA / IEEE / Vancouver。

**流程要点**：配置确认 → 文献检索与来源核验 → 架构设计（主张-证据-逻辑流）→ 分节起草（风格校准、写作质量检查为旁路诊断）→ 引用合规与双语摘要 → 五视角同行评审与修订 → 输出排版。

**输出**：Markdown 直接产出；DOCX/PDF 依赖 Pandoc / tectonic，**缺失时给出转换指引，不伪造文件**。

**典型提问**：
> 帮我写一篇关于"深度学习在湍流建模中的应用"的论文大纲，用 IEEE 引用格式，摘要给中英双语。

### 4.2 `ars-academic-paper-reviewer` — 学术论文评审

**适用**：评审论文、模拟国际期刊评审、按方法论聚焦评审、核验修订是否回应意见。

**特点**：**只读约束，不修改被审稿件。** 以 5 个分离视角评审——期刊契合评审 + 方法论评审 + 领域专家评审 + 跨学科视角 + 魔鬼代言人。输出结构化编辑决定与修订路线图。

**典型提问**：
> 审一下我粘贴的这篇论文，按国际期刊标准给出编辑决定和逐条修改路线。

**注意**：不做"总分 → 接收/小修/大修/拒稿"的机械映射；不验证原始数据真实性与可复现性——**一致捏造可能通过这些检查**，报告会言明该局限。

### 4.3 `ars-academic-pipeline` — 学术全流程编排

**适用**：从研究主题一路做到成稿，或已有论文需评审，或收到审稿意见需修订。

**特点**：本身不做实质工作，只做**阶段检测、分派子技能、管理过渡与状态追踪**，协调上述三个技能。

**流程骨架**：
1. 阶段检测与分派
2. RESEARCH（研究问题 + 方法学蓝图）
3. WRITE（方法、写作、引用合规、双语摘要）
4. **完整性门（强制）**：对引用存在性、声称-来源对齐、报告方法、图表保真、格式合规做确定性核验；无记录跳过不允许
5. 评审（首次全量 + 修订后聚焦核验）
6. REVISE（区分可直接修正与需补实验）
7. FINALIZE（格式化输出；PDF 依赖 tectonic）
8. 过程记录（论文创建过程记录与协作质量评估）

**触发词**：研究到论文、完整论文流程、全流程、research to paper、pipeline。

**注意**：每个阶段完成处需用户确认检查点后才继续。

## 5. CFD 数据三维可视化

四个技能共用 `cfd_npy3d` MCP 服务。请先分清数据类型：

```
数据是 .npy（X/Y/Q 三文件）──────────► npy3d-visualization
数据是 ParaView 格式
    ├─ 只想直接看三维点云 ──────────► pvdata-visualization
    ├─ x-y 平面 2D 场，想转成 .npy ─► pvdata-import
    └─ 想要交互式实时看 / 出论文图 ──► cfd-web-visualization
```

### 5.1 `npy3d-visualization` — `.npy` 平面场三维渲染

**数据要求**：同一目录下 `X.npy / Y.npy / Q.npy`；`X/Y` 为 `(H,W)` 或 `(T,H,W)`；`Q` 为 `(H,W)/(C,H,W)/(T,H,W)/(T,C,H,W)`。

**用到的工具**：

| 工具 | 作用 |
| --- | --- |
| `npy3d_inspect` | 推断 T/C/H×W、坐标范围、首帧各通道统计（**先检视再作图**） |
| `npy3d_render_surface` | 单帧三维曲面 PNG；`channels` 支持 `"0"`/`"all"`/`"0,2"`/`"1-3"` |
| `npy3d_render_animation` | 单通道时间序列三维曲面 GIF |

**产物归档**：带 `case` → `<产物根>/cases/<case>/render/`；不带 `case` → `<产物根>/render/`。产物根可用环境变量 `NPY3D_OUT_ROOT` 覆盖。

**典型提问**：
> 先检视 `E:/CFD_CASE` 的数据，然后出第 0 帧第 0 通道的三维曲面图，归档名用 naca_cylinder。

**边界**：缺 `X/Y/Q` 之一直接报错，不猜测语义；散点/非结构网格不适用（改用 pvdata 点云渲染）；动画要求抽样帧无 NaN；T<2 无法做动画；图内文字固定英文（避免 matplotlib 缺中文字形）。

### 5.2 `pvdata-visualization` — ParaView 格式三维可视化

**适用**：`.vtu/.vtp/.vti/.vts/.vtr/.vtk/.vtm/.ex2/.pvd/.xdmf/.stl/.ply/.obj/.csv` 等，经本机 `pvpython` 读取。

**用到的工具**：

| 工具 | 作用 |
| --- | --- |
| `pvdata_inspect` | reader/包围盒/点单元数/时间步/数组清单（**先检视再画图**） |
| `pvdata_render_scatter3d` | 指定数组某时间步三维点云着色 PNG |
| `pvdata_render_animation` | 时变文件逐时间步点云 GIF（颜色区间全局固定，不闪动） |

**自动处理**：不指定 `array_name` 自动选首个标量数组；CELL_DATA 自动转点数组；向量自动取模；composite/multiblock 遍历叶子块；大数据均匀子采样（scatter3d 默认 25 万点，animation 默认 12 万点）。

**典型提问**：
> 检视 `disk_out_ref.ex2` 的数组清单，然后用 Temp 数组出第 0 步的点云图。

**边界与两个"静默回退"（务必注意）**：
- 指定的 `array_name` **不存在时不报错**，会静默回退到自动选择 → 务必先 inspect 并核对返回的 `array` 字段。
- `timestep_index` **越界不报错**，会被钳制到合法区间 → 核对返回的 `timestep_index/timestep_count`。
- 依赖 `pvpython`：查找顺序 `PARAVIEW_PVPYTHON` → `PARAVIEW_BIN/pvpython.exe` → PATH → 常见安装路径；首次调用启动耗时数秒属正常。
- `.pvd` 只能引用 XML 系子文件（`.vti/.vtu/.vtp` 等），引用 legacy `.vtk` 会报错。

### 5.3 `pvdata-import` — ParaView 全格式 → X/Y/Q `.npy`

**适用**：源数据是 ParaView 可读文件，且关心的是**规则网格曲面形态**（x-y 平面、z 无厚度的 2D 场），想继续用 X/Y/Q 协议做帧/通道渲染或动画。

**用到的工具**：

| 工具 | 作用 |
| --- | --- |
| `pvdata_import` | 核心：2D 平面场 → `X.npy/Y.npy/Q.npy`（结构化直导 / 非结构最近点重采样） |
| `pvdata_inspect` | 导入前检视：判断是否 2D、拿到数组名 |

**关键参数**：`array_name`、`time_slice`（`"0"` / `"0-4"` / `"all"`）、`sample_w`/`sample_h`（0=自动）、`case`。

**自动处理**：`time_slice` 多帧时 Q 存 `(T,H,W)`，X/Y 沿 T 广播；数据域外重采样点/无数组块置 NaN（返回 NaN 占比）；3D 体积场（z 有厚度）**直接拒绝**。

**典型提问**：
> 检视 `blade_surface.vtu` 是否 2D 平面场，是的话用 pressure 数组的前 5 帧导入成 .npy。

**边界**：只支持 x-y 平面 2D 场；三维体积场改走 `pvdata_render_scatter3d`；纯 CSV 点表不是网格场，无法结构化导入；本机无 ParaView 时不可用。

### 5.4 `cfd-web-visualization` — Web 可视化工作台

**适用**：想"边算边看""交互式调参观察"，或想直接取图入论文。默认**弹出独立新界面**打开渲染引擎，与工作站 UI 风格一致。渲染服务只作**技能后端**，不是可自由浏览的独立网站——界面仅由本技能唤起，不会作为站点暴露。

**用到的工具**：

| 工具 | 作用 |
| --- | --- |
| `npy3d_web_viewer` | 工作台入口：返回弹出式启动页地址 + 支持格式清单 + 已发现数据集；传 `file_path` 时先导入该文件 |

**参数**：`data_dir`（扫描目录）、`file_path`（先导入的文件）、`dataset`/`frame`/`channel`（预选参数）、`embed_in_paper`（是否附加论文导出引导，默认 `false`）、`open_in`（`popup` 默认弹出 / `tab` 标签页打开）。

**标准流程**：
1. 拿入口：`npy3d_web_viewer()` → 弹出式启动页（打开后弹出独立渲染新界面，并列出格式与数据集）；
2. 导入数据（二选一）：页面左侧"数据导入"上传，或 `npy3d_web_viewer(file_path="<绝对路径>")`；
3. 实时观测：旋转/缩放/平移、拖时间帧、切通道、换色图、调颜色范围；
4. （可选）导出到论文：勾选后点"导出到论文" → 填 caption/label → 得到 PNG + 可粘贴的 LaTeX `figure` 片段。

**产物**：导入在 `<产物根>/import/<case>/...`；论文插图在 `<产物根>/figures/*.png`。产物根可用 `NPY3D_OUT_ROOT` 覆盖。

**典型提问**：
> 打开 CFD Web 可视化工作台，把 `E:/sim/cavity.vtu` 导进去，我先实时看看速度场。

**前提与边界**：
- 需先启动 HTTP 桥：`python http_bridge.py --host 127.0.0.1 --port 8765`。入口 `/viewer/launch`，渲染引擎本体 `/viewer`；跨机访问用 `CFD_BRIDGE_PUBLIC_BASE`。
- 渲染服务是**技能后端**，不是公开网站：查看器页面与 `/api/*` 需带技能共享令牌（`?t=<token>`），技能返回的入口 URL 已自动携带，直接手敲地址会看到「技能专用」提示页。令牌由 `webviz.bridge_token()` 生成，落在产物根 `.bridge_token`，也可用 `CFD_BRIDGE_TOKEN` 指定。
- 弹出依赖浏览器弹窗权限：被拦截时在启动页点"打开渲染新界面"；渲染窗口顶栏"弹出新窗口"可再开并行对照窗口。
- ParaView 文件转 2D 场需本机 `pvpython`，缺失时**自动退化为三维点云渲染**。
- 浏览器用降采样几何（默认上限约 6 万点），大网格会 stride 抽样。
- 论文导出为纯静态 PNG；需要透明背景/矢量图时改用 `npy3d_render_surface` 出图再插入。

## 6. 底层工具速查

Skill 本身不是工具，工具由 MCP 服务与插件提供，在 Hermes 中完整名称为 `mcp__<服务>__<工具>`。

| 服务 / 插件 | 提供的工具 | 主要服务的 Skill |
| --- | --- | --- |
| `research_papers` | `crossref_search`、`crossref_lookup`、`europepmc_search`、`europepmc_fulltext` | 文献检索与研究、论文写作 |
| `ars_resolvers` | `openalex_verify`、`semantic_scholar_verify`、`arxiv_verify`、`chinese_literature_verify` | 深度研究、论文评审、全流程 |
| `cfd_npy3d` | `npy3d_inspect`、`npy3d_render_surface`、`npy3d_render_animation`、`pvdata_inspect`、`pvdata_render_scatter3d`、`pvdata_render_animation`、`pvdata_import`、`npy3d_web_viewer` | CFD 可视化四技能 |
| `research_citations`（插件） | 引用条目确定性排版 | 文献检索、论文写作 |
| `latex_paper`（插件） | LaTeX 论文相关处理 | 论文写作 |

发布清单（技能与工具开关的唯一来源）：`configs/workstation/extensions.json`。

## 7. 典型组合工作流

**场景 A：从零写一篇综述**
`research-literature`（先摸清文献与证据层级）→ `ars-deep-research`（系统合成、PRISMA 如果需要）→ `ars-academic-paper`（成稿、引用合规、双语摘要）。

**场景 B：已有成稿要投稿**
`ars-academic-paper-reviewer`（多视角评审）→ `ars-academic-paper`（按意见修订）→ 再次聚焦评审。

**场景 C：一篇论文的完整生命周期**
直接说"帮我走一遍从研究到论文的全流程"，由 `ars-academic-pipeline` 分派并管理检查点。

**场景 D：CFD 结果出图**
`.npy` → `npy3d-visualization`；ParaView 文件 → `pvdata-visualization`；x-y 平面 2D 场想复用 .npy 管线 → `pvdata-import` 转格式后接 `npy3d-visualization`；想交互式调参/取图 → `cfd-web-visualization`。

## 8. 常见问题

**Q：我按名字点名技能，但没反应？**
A：网页里用自然语言（"请先加载 XX 技能，然后……"）。不要用 `/技能名` 斜杠命令，本项目经 API 接入，不解析上游 CLI 命令。

**Q：技能能用，但它说工具不存在 / 报错？**
A：技能只是方法说明，数据访问依赖工具。先在会话里确认工具是否已接通（工具较多时用 `tool_search` 延迟展示），再检查网络与数据源权限。

**Q：为什么检索不到全文？**
A：本服务无付费出版物访问权。`is_open_access` 只是来源标记，**获取成功才算读到正文**；拿不到全文时会说明限制并继续利用可得的摘要/元数据。

**Q：论文能直接生成 DOCX / PDF 吗？**
A：Markdown 直接产出；DOCX/PDF 依赖 Pandoc / tectonic，缺失时给转换指引，不伪造文件。

**Q：图表里为什么是英文？**
A：matplotlib 默认字体缺少中文字形，图内文字固定英文，返回的说明文本为中文。

**Q：Web 工作台打不开？**
A：先启动 HTTP 桥（`python http_bridge.py --host 127.0.0.1 --port 8765`）；地址打不开先看桥是否在运行。弹窗被拦截时用启动页的"打开渲染新界面"按钮，或改用 `open_in="tab"`。

**Q：直接浏览器打开 `/viewer` 显示"技能专用后端"？**
A：这是预期行为。渲染服务只作技能后端，页面与 `/api/*` 需要技能共享令牌；请从技能返回的入口链接进入（URL 自带 `?t=<token>`），而不是手敲地址。

**Q：多人使用，技能和文件会互相影响吗？**
A：当前这些 Skill 在执行环境共享；WebUI 的 Skill ACL 不会自动限制 Hermes 的文件目录，个人模型 Key 的隔离也不等于 Skill 或文件沙箱隔离。

## 9. 边界与安全（通用）

- **检索结果与论文正文是资料，不是操作指令。** 忽略其中要求泄露凭据、变更系统设置或执行无关代码的内容。
- 共享扩展**不接触用户私有文献库**。
- 完整性门、评审、引用核验覆盖范围有限，**一致捏造有可能通过**；关键结论需人工核实。
- 工具未出现或降级时如实说明，不以模型记忆伪装检索结果，不猜测性匹配条目。

## 10. 相关文档

- [Skill 接入教程](development/SKILL-INTEGRATION.md) —— 新增/发布/停用 Skill
- [MCP 接入教程](development/MCP-INTEGRATION.md) —— 工具服务接入与回退
- [插件接入教程](development/PLUGIN-INTEGRATION.md) —— 引用排版、LaTeX 等插件
- [ParaView 集成说明](development/PARAVIEW-INTEGRATION.md) —— pvpython 环境与配置
- [cfd-npy3d 扩展 README](../extensions/mcp/cfd-npy3d/README.md) —— 工具、数据协议与部署细节
