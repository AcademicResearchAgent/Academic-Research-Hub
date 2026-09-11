# 科研智能体工作站

面向文献检索与综述、研究问题分析、实验方案设计和论文写作的科研助手。当前实现基于 Hermes + Open WebUI，支持多厂商模型，实际架构见 [架构说明](docs/development/ARCHITECTURE.md)。

## 新同事从这里开始

1. 阅读 [开发指南](docs/development/DEVELOPMENT.md) 和 [实际架构与部署对应关系](docs/development/ARCHITECTURE.md)。
2. 安装 Git、Python 3.11；前端开发使用 Node.js 22，完整构建建议使用 Linux / WSL2 / Docker。Hermes 支持到 Python 3.13，但当前 UI 后端要求低于 3.13。
3. 在项目根目录运行以下命令。它们准备本地源码和部署材料，不连接生产服务器：

```powershell
python scripts/prepare_sources.py
python scripts/prepare_sources.py --check
python scripts/package_deploy.py
```

团队仓库：[AcademicResearchAgent/Academic-Research-Hub](https://github.com/AcademicResearchAgent/Academic-Research-Hub)。上游源码使用精确提交加补丁管理，不把两个大型第三方仓库直接复制进主仓库。新的团队成员克隆本项目后执行准备命令即可恢复源码；日常开发使用功能分支，通过 PR 审查后合并到 `main`。

## 目录职责

```text
configs/workstation/       产品文案、科研助手 SOUL，唯一配置来源
extensions/               项目 Skill、论文 MCP 服务和原生插件
reference/hermes-agent/    固定版本的执行引擎源码，准备脚本恢复
reference/open-webui/      固定版本的 Svelte 前端和 Python 后端源码
patches/                  我们对上游源码的定制，纳入主仓库审查
overlays/                 源码构建和现有镜像构建共用的修复逻辑
scripts/                  源码准备、补丁生成、部署材料打包
tests/                    截图等行为测试
deploy/hermes/            现有服务器部署、验证和历史排障脚本
deploy/workspaces/        项目文件区、隔离运行器、迁移与部署验收
docs/development/         开发流程、架构、上线与回退边界
docs/                     论文检索调研及测试证据
sources.lock.json         上游提交和生产镜像锁定信息
.build/                   本地生成材料，不提交
```

## 去哪里修改

| 工作 | 修改入口 |
| --- | --- |
| 助手身份、回答风格 | `configs/workstation/SOUL.md` |
| 产品名称、登录说明、科研建议、中文术语 | `configs/workstation/research-copy.json` |
| 模型目录、厂商区域与 API Key 配置 | `configs/workstation/model-catalog.json`、`overlays/open-webui/workstation_models/` |
| 模型自动检测、可用性标注 | `overlays/open-webui/ModelAvailability.ts`、`workstation_models/availability.py`，见 [模型选择说明](docs/development/MODEL-SELECTION.md) |
| 思考流、等待提示和工具执行状态 | [流式显示接入与验收](docs/development/STREAMING.md) |
| 检索式、来源、题名与工具结果实时显示 | [研究过程接入与验收](docs/development/RESEARCH-ACTIVITY.md) |
| 项目、文件区、资源管理器与右侧预览编辑 | [工作区开发与验收](docs/development/WORKSPACES.md)，已部署正式服务器 |
| 登录、聊天、科研资源等界面行为 | `reference/open-webui/src/` |
| 账号、模型代理、文件和知识库接口 | `reference/open-webui/backend/open_webui/` |
| Agent 工具、会话、提示词组装 | `reference/hermes-agent/tools/`、`agent/`、`gateway/` |
| 上线和运行检查 | [部署说明](deploy/hermes/README.md) |

论文检索现有 `extensions/mcp/paper-search`，通过 MCP 接入 Crossref 元数据、Europe PMC 检索及开放正文片段；配套文献检索 Skill 和引用排版插件。新增业务在 `extensions/` 中实现并测试，不把提示词中写出的用途当成已完成的模块。

扩展能力的三个接入教程：[Skill](docs/development/SKILL-INTEGRATION.md)、[MCP](docs/development/MCP-INTEGRATION.md)、[插件](docs/development/PLUGIN-INTEGRATION.md)。包含源码约定、现有服务器发布、验证、回退，以及 Hermes 与 Open WebUI 两层接口的区别。使用者请先看 [Skill 使用手册](docs/SKILL-USAGE.md)，其中汇总了内置技能清单、自然语言调用方式、产出与边界。

本地 `LLM_API.md`、`server.md`、个人材料、账号录入脚本和运行数据已列入忽略规则。新同事通过管理员取得自己的开发凭据，不复制生产账号库。上游许可与版权声明保留在源码中。

文件上传、网页引用与截图入口的修复及部署步骤见 [附件功能修复记录](docs/development/ATTACHMENT-FIXES.md)。本地文档检索模型已在生产启用；HTTP 下截图按钮提供文件选择与粘贴指引，浏览器直接截屏需 HTTPS 或 localhost。

模型选择支持 Qwen、Kimi、DeepSeek 和 GLM，新增型号首次使用时验证个人 API Key，并按账号加密保存。用户直接访问 **https://42.193.15.167** 即可登录并填写 Key，原 HTTP 9119 入口自动跳转，无需 SSH。实现见 [模型选择与密钥管理](docs/development/MODEL-SELECTION.md)，证书自动续期和部署维护见 [HTTPS 运维说明](docs/development/HTTPS.md)。
