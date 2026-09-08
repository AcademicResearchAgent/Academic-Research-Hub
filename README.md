# 科研智能体工作站

面向文献检索与综述、研究问题分析、实验方案设计和论文写作的科研助手。需求依据见 [MainTask.md](MainTask.md)，当前实现基于 Hermes + Open WebUI + DeepSeek，尚未建设独立的 Django / Vue / MySQL 应用。

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
reference/hermes-agent/    固定版本的执行引擎源码，准备脚本恢复
reference/open-webui/      固定版本的 Svelte 前端和 Python 后端源码
patches/                  我们对上游源码的定制，纳入主仓库审查
overlays/                 源码构建和现有镜像构建共用的修复逻辑
scripts/                  源码准备、补丁生成、部署材料打包
tests/                    截图等行为测试
deploy/hermes/            现有服务器部署、验证和历史排障脚本
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
| 登录、聊天、科研资源等界面行为 | `reference/open-webui/src/` |
| 账号、模型代理、文件和知识库接口 | `reference/open-webui/backend/open_webui/` |
| Agent 工具、会话、提示词组装 | `reference/hermes-agent/tools/`、`agent/`、`gateway/` |
| 上线和运行检查 | [部署说明](deploy/hermes/README.md) |

新增论文检索业务应有独立模块与测试，再通过工具接口接入执行引擎；目前没有已实现的独立论文检索服务，不要把提示词中写出的用途当成已完成的模块。

本地 `LLM_API.md`、`server.md`、个人材料、账号录入脚本和运行数据已列入忽略规则。新同事通过管理员取得自己的开发凭据，不复制生产账号库。上游许可与版权声明保留在源码中。

文件上传、网页引用与截图入口的修复及部署步骤见 [附件功能修复记录](docs/development/ATTACHMENT-FIXES.md)。本地文档检索模型已在生产启用；HTTP 下截图按钮提供文件选择与粘贴指引，浏览器直接截屏需 HTTPS 或 localhost。
