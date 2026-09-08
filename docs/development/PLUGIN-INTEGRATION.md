# 插件接入教程

核对日期：2026-09-08。适用本项目锁定版本，精确提交见 `sources.lock.json`。本教程区分 Hermes 执行插件与 Open WebUI 界面插件，二者不能互相安装。

## 1. 先选择插件所在层

| 需求 | 本项目建议入口 |
| --- | --- |
| 让 Agent 执行一个内部 Python 能力 | Hermes 原生插件，注册工具 |
| 多个 Agent / 客户端共用外部服务 | 优先独立 MCP，见 [MCP 教程](MCP-INTEGRATION.md) |
| 描述科研流程、规范和示例 | Skill，见 [Skill 教程](SKILL-INTEGRATION.md) |
| 给聊天页面增加操作按钮 | Open WebUI Action Function 或前端定制 |
| 修改进入 / 离开网页聊天链路的消息 | Open WebUI Filter Function，按当前路由实际验收 |
| 新增模型接入 | 优先本项目模型目录与密钥路由；单独评估 Pipe 对现有路由的影响 |

Hermes 原生插件可通过 `register(ctx)` 注册工具、钩子等；Open WebUI 的 Tools 是模型可调用的 Python 能力，Functions 包括 Pipe、Filter、Action 等界面或链路扩展。[Hermes 插件开发文档](https://github.com/NousResearch/hermes-agent/blob/693641aa8b4359c602283bdbbc14041e03bc47bc/website/docs/developer-guide/plugins/index.md)、[Open WebUI 扩展概览](https://docs.openwebui.com/features/extensibility/)。

## 2. 本项目的运行示例

[`extensions/plugins/research-citations/`](../../extensions/plugins/research-citations/) 包含：

```text
plugin.yaml       名称、版本、提供的工具
__init__.py       register(ctx)、工具 schema 和处理函数
```

插件名 `research-citations`，版本 `1.0.0`；注册工具 `research_citation`，工具集名 `research_citations`。它将**已经检索到的**论文元数据排成普通引用条目，优先生成 DOI 链接，拒绝格式错误的 DOI 和不合法链接。

它不会访问网络或文件，不验证论文真实性，不补造缺失字段，也不宣称符合 APA、GB/T 或期刊样式。返回的 `verified: false` 特别提醒调用者：排版不是核验。正式多样式引用应另接 CSL / citeproc 类实现并补测试。

## 3. 新建 Hermes 插件

在 `extensions/plugins/<插件名>/` 放置清单：

```yaml
name: research-citations
version: "1.0.0"
description: Format supplied scholarly metadata without inventing missing fields.
provides_tools:
  - research_citation
```

入口结构如下，完整可运行代码以仓库示例为准：

```python
import json

def handle_reference(params, **kwargs):
    title = str(params.get("title", "")).strip()
    if not title:
        return json.dumps({"success": False, "error": "title is required"})
    return json.dumps({"success": True, "reference": title, "verified": False})

def register(ctx):
    ctx.register_tool(
        name="research_citation",
        toolset="research_citations",
        schema={
            "name": "research_citation",
            "description": "Format supplied paper metadata; does not verify it.",
            "parameters": {
                "type": "object",
                "properties": {"title": {"type": "string"}},
                "required": ["title"]
            }
        },
        handler=handle_reference
    )
```

开发另一个插件时更换插件名、工具名和工具集名，避免覆盖示例。schema 的 `description` 才是模型看到的工具说明；参数校验、错误返回和超时要在实现中处理，不能依赖模型总能传对参数。处理函数接受 `**kwargs`，避免新增调用上下文时破坏兼容。

只使用上游公开注册接口，避免导入正在重构的内部模块。需要执行钩子时使用当前文档中存在的 hook 名称，回调接受 `**kwargs`；不要用钩子无差别记录完整请求、用户 Key 或其他人的研究内容。原生插件和 MCP stdio 子进程不是用户沙箱。

## 4. 启用与发布

将插件名称加入 [`configs/workstation/extensions.json`](../../configs/workstation/extensions.json) 的 `plugins` 数组，将插件工具集名称加入 `api_toolsets`。部署器会更新：

```yaml
plugins:
  enabled:
    - research-citations
platform_toolsets:
  api_server:
    # 保留已有工具集，再追加：
    - research_citations
```

这些是配置片段，不要拿它们覆盖整个配置。部署器合并已有允许列表，并移除本次显式启用插件在 `plugins.disabled` 中的同名项；其他插件的策略保持原样。

普通原生插件默认不加载，仅把目录复制到服务器不够，必须加入允许列表。上游也提供 `hermes plugins enable <name>` / `disable <name>`；本项目正式部署由配置清单统一管理。[Hermes 官方插件使用说明](https://github.com/NousResearch/hermes-agent/blob/693641aa8b4359c602283bdbbc14041e03bc47bc/website/docs/user-guide/features/plugins.md)。

运行 [MCP 教程中的发布命令](MCP-INTEGRATION.md#4-发布与验证)。插件复制到 `/home/ubuntu/haudi-hermes/state/plugins/research-citations`，重启现有 Hermes 服务加载；不需要向 UI 容器安装这份代码。

在仓库中新增插件后，更新业务测试与部署验收预期；当前验收脚本明确验证示例插件，不会自动证明所有新增插件都可用。

## 5. 验证、更新和移除

本地运行 `python -m unittest discover -s tests -p test_extensions.py -v`，覆盖引用缺失字段、恶意或错误链接、DOI 格式和公开注册入口。服务器验收通过 Hermes 真实工具注册表调用引用插件。

还可在服务器独立检查插件：

```bash
cd /home/ubuntu/haudi-hermes/source
HERMES_HOME=/home/ubuntu/haudi-hermes/state ../venv/bin/hermes plugins doctor ../state/plugins/research-citations --ci
```

Doctor 会导入并执行注册代码，是诊断工具，不是隔离沙箱；只对已审查源码运行。[官方 Plugin Doctor 说明](https://github.com/NousResearch/hermes-agent/blob/693641aa8b4359c602283bdbbc14041e03bc47bc/website/docs/developer-guide/plugins/index.md)。

网页中可要求：“先用论文 MCP 核实 DOI，再调用 research_citation 排版。”既要看到回答，也要确认工具执行记录存在。新增 slash command 或 CLI 子命令不会自动成为网页按钮。

更新插件版本和代码后重新发布，回退使用 [MCP 运维步骤](MCP-INTEGRATION.md#6-运维与回退)。停用插件时同时移除仓库启用清单、服务器 `plugins.enabled` 中的名称，并加入 `plugins.disabled`，重启后确认工具不再出现。当前发布器只启用清单内组件，不会自动清理未列出的旧插件。

从第三方仓库安装时固定完整不可变提交，记录来源与版本，再在开发 profile 验证；不要在生产自动追踪 `main/latest`。上游支持原生插件安装固定提交，也有 `plugin.json` 可移植插件兼容层，但当前只是 Agent Plugins 的部分能力支持，不能当作任意插件市场通用安装器。

## 6. Open WebUI 插件的标准接入方式

Open WebUI 原生 Tools 通常通过 Workspace → Tools 管理；Functions 由管理员管理，代码中使用顶层 `Pipe`、`Filter` 或 `Action` 类。应根据当前页面权限和版本选择对应入口。[官方 Tools & Functions](https://docs.openwebui.com/features/extensibility/plugin/)、[Functions 文档](https://docs.openwebui.com/features/extensibility/plugin/functions/)。

例如仅针对网页消息预处理的最小 Filter：

```python
"""
title: Research Message Normalizer
version: 0.1.0
"""

class Filter:
    async def inlet(self, body: dict) -> dict:
        # 示例只去除末条用户文字两端空白；不改附件或其他角色消息。
        messages = body.get("messages") or []
        if messages and messages[-1].get("role") == "user":
            content = messages[-1].get("content")
            if isinstance(content, str):
                messages[-1]["content"] = content.strip()
        return body
```

此示例仅用于说明接口，**未安装到生产**。实际开发时在仓库单独保存 WebUI 插件源码和测试，在独立开发实例导入，先限定到测试模型。验证文字、附件、流式响应、用户权限和失败处理，再启用；不要直接修改运行容器或只保留数据库中的一份代码。[官方 Filter 文档](https://docs.openwebui.com/features/extensibility/plugin/functions/filter/)。

当前项目的限制：

- WebUI Tool 注册不等于 Hermes 获得工具。`ws-*` 路由不会转发 WebUI 工具 schema 和执行器，Agent 工具应放在 Hermes / MCP 层。
- WebUI Filter 只能观察它所在的网页请求链路；不能据此声称能拦截 Hermes 内部每一步 LLM 调用。`request` 等上游 hook 在自定义路由上需单独验收。
- Pipe 可能新增独立模型入口并自行处理请求，不能绕过本项目个人 Key 验证和账号路由。现有模型扩展首先看 [模型管理说明](MODEL-SELECTION.md)。
- WebUI 的 Action / 富界面机制与 Hermes 原生桌面或 dashboard 插件是不同协议，不能直接互装。
- WebUI 插件权限与 Hermes 插件共享运行权限没有自动映射。接入私有科研数据库时，要在实际执行层落实身份、授权和凭据隔离。

## 7. 同事交付检查

提交插件源码、清单和依赖变更，附一条真实调用验收记录及回退方式。说明它运行在 Hermes 还是 WebUI、是否读写外部系统、使用哪些凭据、是否共享数据。凭据、日志、账号数据库和服务器备份不进 Git。修改上游源码时仍按项目补丁流程交付，不能只改 `reference/`。
