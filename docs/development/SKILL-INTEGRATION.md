# Skill 接入教程

核对日期：2026-09-08。适用版本：`sources.lock.json` 中的 Hermes `693641aa…`、Open WebUI `0a7c1583…`（0.11.3）。本文中“项目约定”是本仓库的组织方式，不是上游新增标准。

## 1. 放在哪一层

科研方法、操作步骤和输出要求放在 **Hermes Skill** 中，跟随实际执行任务的 Agent 加载。当前链路是浏览器 → Open WebUI → 工作站模型路由 → Hermes → 工具；不需要为每个 Skill 改聊天页面或重建 UI 镜像。

Hermes 使用 Agent Skills 格式：一个目录、一份带 YAML frontmatter 的 `SKILL.md`，按需附带 `scripts/`、`references/`、`assets/`。Skill 给出方法，真正访问数据库依赖已接通的工具。[Hermes 官方 Skill 文档](https://github.com/NousResearch/hermes-agent/blob/693641aa8b4359c602283bdbbc14041e03bc47bc/website/docs/user-guide/features/skills.md)、[Agent Skills 规范](https://agentskills.io/specification)。

## 2. 本项目已经提供的例子

源码：[`extensions/skills/research-literature/SKILL.md`](../../extensions/skills/research-literature/SKILL.md)。

它指导 Agent 使用论文 MCP 检索、核对 DOI、读取可得正文，并明确记录“元数据 / 摘要 / 全文片段”三个证据层级。最后可调用引用插件排版。它不会赋予付费数据库权限，也不把前几条搜索结果称为系统综述。

```text
extensions/skills/research-literature/SKILL.md    团队维护的源文件
configs/workstation/extensions.json             发布清单
服务器 state/skills/research-literature/         运行时副本
```

服务器根目录为 `/home/ubuntu/haudi-hermes`，服务设置 `HERMES_HOME=/home/ubuntu/haudi-hermes/state`。所以生产目录是 `state/skills`，不是登录用户默认的 `~/.hermes/skills`。

## 3. 新增自己的 Skill

例如新增 `experiment-review`，在 `extensions/skills/experiment-review/SKILL.md` 写入：

```markdown
---
name: experiment-review
description: 审阅用户提供的实验方案，检查对照、测量指标和可重复性。
---

# 实验方案审阅

## 适用场景
用户已经提供实验方案，并要求检查设计是否支持其研究问题。

## 流程
从原方案提取假设、自变量、测量指标和对照设置。
指出会影响结论的缺失信息；区分可直接修正的问题和需要补充实验的问题。
涉及外部研究依据时使用可用检索工具，给出真实来源。

## 产出
提供按影响程度排列的具体修改建议，不虚构样本量计算或实验结果。
```

项目约定：目录名与 `name` 相同，使用小写字母和连字符；描述写清触发条件。较长的学科规范放入 `references/` 并从正文链接。脚本应能独立测试，不把 API Key 写入 Markdown 或脚本。

将名称加入 [`configs/workstation/extensions.json`](../../configs/workstation/extensions.json) 的 `skills` 数组，保留已有条目。新增依赖或工具时，同时维护相应 MCP / 插件配置；不能只在 Skill 中写一个不存在的工具名。

## 4. 发布到现有服务器

在仓库根目录 PowerShell 中运行。前提：已按项目部署说明配置 SSH 别名、私钥和固定 known_hosts；服务器已存在本项目的 Hermes、venv 和 uv。

```powershell
python -m unittest discover -s tests -p test_extensions.py -v
python scripts/package_extensions.py
python deploy/hermes/upload.py .build/extensions.zip /home/ubuntu/haudi-hermes/extensions.zip
python deploy/hermes/upload.py deploy/hermes/deploy-extensions.py /home/ubuntu/haudi-hermes/deploy-extensions.py
python deploy/hermes/remote.py deploy/hermes/deploy-extensions.sh
```

这是三类扩展共用的发布流程。部署器根据清单安装 Skill 和插件、合并 MCP 配置，保留已有其他扩展。覆盖同名项目 Skill 前会备份运行时副本；服务器上由 Agent 修改的同名文件不会自动反向提交到 Git，需人工比较并合入源码。

发布器按归档内容生成不可变 release ID；成功记录和回退步骤见 [MCP 教程](MCP-INTEGRATION.md#6-运维与回退)。更新 `skills` 清单不会自动删除旧目录；停用步骤见下文。

## 5. 验证和使用

服务器终端执行以下命令可直接验证 Skill 加载，不调用模型：

```bash
cd /home/ubuntu/haudi-hermes/source
HERMES_HOME=/home/ubuntu/haudi-hermes/state ../venv/bin/python -c 'import json; from tools.skills_tool import skill_view; r=json.loads(skill_view("research-literature")); assert not r.get("error"); assert "crossref_search" in json.dumps(r); print("Skill load: PASS")'
```

网页中新建科研任务，选择已配置个人 API Key 的模型，输入：

> 请先加载 research-literature 技能，然后检索 CRISPR 的相关论文，提供来源、DOI，并区分你读到的是摘要还是正文。

Hermes 可用 `skills_list` 发现、`skill_view` 加载。较多工具可能通过 `tool_search` 延迟展示；不要仅凭首屏工具列表断言不存在。上游 CLI / 消息网关支持 `/技能名`，但本项目通过 API 接入，网页里应使用上述自然语言调用，不能把斜杠命令的解析行为视为已经实现。

## 6. Open WebUI 自带的 Skills 怎么用

Open WebUI 自身也有 Workspace → Skills，支持创建 / 导入 Markdown、访问控制，以及 `$` 提及和模型绑定。显式提及可将完整内容放入消息；模型绑定的按需加载依赖 **Open WebUI 的 `view_skill` 工具**。[Open WebUI 官方 Skills 文档](https://docs.openwebui.com/features/workspace/skills/)。

这与 Hermes 的 `skill_view`、服务器 `state/skills` 是两套存储和加载机制。本项目 `ws-*` 模型路由只转发消息等白名单字段，不把 WebUI 的工具执行循环搬到 Hermes；因此不能把 WebUI 中“已绑定 Skill”视为 Hermes 一定能按需读取它。纯文本注入可以沿消息传递，但依赖 WebUI 工具的流程必须单独验收。

**团队正式科研流程以仓库内 Hermes Skill 为主。** 网页 Skill 可用于个人临时文字规范；不依靠网页导入来安装脚本、系统依赖或 MCP。需要两端同步时应另写同步器，维护标识、版本、权限和冲突策略；当前没有此同步器。

## 7. 更新、停用和常见问题

- 更新：修改仓库文件、运行测试、重新发布；新建任务验证。重启 Agent 会打断正在执行的任务，应在合适窗口操作。
- 停用单个项目 Skill：从发布清单移除，并将服务器对应目录移动到 `state/skills` **之外**的备份目录，然后重启。只从清单移除不会删除运行时文件；本次发布器不做自动清理。
- 找不到 Skill：检查 `HERMES_HOME`、frontmatter、目录名、`platform_toolsets.api_server` 是否含 `skills`，以及上游技能禁用设置。
- 能加载但做不了：检查实际工具名、依赖、数据源权限和网络。外部 Skill 中的工具名称不一定能在当前引擎使用。
- 多用户：当前这些 Skill 在执行环境共享；WebUI 的 Skill ACL 不会自动限制 Hermes 的文件目录。个人模型 Key 的隔离也不等同于 Skill 或文件沙箱隔离。
