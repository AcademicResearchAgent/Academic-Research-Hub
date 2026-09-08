# 科研智能体工作站

根据项目 `MainTask.md` 定位，面向科学文献调研与实验方案设计，覆盖文献检索、摘要综述、研究空白分析、实验设计建议、论文写作辅助和可视化报告。
交互界面使用 Open WebUI，Agent 执行引擎使用 Hermes。

服务器：`42.193.15.167`，SSH 用户：`ubuntu`。

## 打开网页

直接访问 **https://42.193.15.167**，使用已录入的本站科研账号登录。用户可以在网页中配置个人 API Key，无需 SSH；原 HTTP 9119 地址自动跳转。证书自动续期，详见 [HTTPS 运维说明](../../docs/development/HTTPS.md)。

仅开发者排障时，也可双击同目录的 `open-hermes.cmd`，或执行 `python deploy/hermes/open-hermes.py`。
脚本会在后台建立 SSH 隧道，打开 http://127.0.0.1:9119 。使用隧道时，电脑重启或隧道断开后重新运行即可。

管理员登录信息保存在服务器 `/home/ubuntu/haudi-hermes/openwebui/access.json`。
下载到本机需要用户明确授权；授权后保存到同目录的 `openwebui-access.json`（已加入 Git 忽略规则）。
登录后选择具体型号并配置个人 API Key；默认显示 DeepSeek V4 Flash，界面默认中文。原来单独显示的“科研助手”入口已从选择列表隐藏，内部基础连接记录保留。

开发入口和源码结构见 [项目 README](../../README.md) 与 [开发指南](../../docs/development/DEVELOPMENT.md)。本目录保留现有部署路径和历史运维脚本，不是日常产品源码目录。

登录页已标注“登录科研智能体工作站”“本站科研账号（邮箱格式）”，并说明账号由管理员统一创建、邮箱仅作为登录名。
首页使用“新科研任务”“科研任务记录”“研究笔记”“科研资源”等表述，六个任务建议对应 MainTask 的科研工作流。
当前界面通过 `haudi-openwebui:0.11.3-research-v5` 定制镜像持久化，包含完整源码构建的前端和个人模型配置。研究笔记和文献资料库的空状态、搜索及操作提示也使用一致术语。

统一文案在 [`configs/workstation/research-copy.json`](../../configs/workstation/research-copy.json)，科研助手身份说明在 [`configs/workstation/SOUL.md`](../../configs/workstation/SOUL.md)。运行 `python scripts/package_deploy.py` 将其以远端兼容文件名打包到 `.build/deploy/`，上传后再执行所需部署脚本；远端身份最终写入 `state/SOUL.md`。
身份说明要求可核查引用、区分事实与推断、区分预期结果与实测结果，并按实际工具情况说明能力。
文献业务用途文案不代表全部模块已经实现；学术数据库适配、运营人员/分析师等细分角色和专用报告模块仍需继续建设。本地知识库嵌入模型已于 2026-09-08 安装并通过附件引用验收。

浏览器 → nginx（公网 HTTPS 443）→ Open WebUI（`127.0.0.1:9119`）→ Hermes API（`127.0.0.1:8642`）。
Hermes 执行服务器上的终端、文件和浏览器工具。

模型选为 `deepseek-v4-flash`。2026-09-08 经用户授权，已通过 SSH 将 `LLM_API.md` 中的模型密钥写入服务器 `state/.env`（权限 600），并重启 Hermes。
已通过 Open WebUI 登录后的聊天接口验证 Open WebUI → Hermes → DeepSeek 的真实流式对话，约 9.7 秒收到“科研助手已连接，可以开始研究任务。”。
Open WebUI 与 Hermes 之间使用服务器生成的独立连接密钥。

## 安装位置

| 内容 | 位置 |
| --- | --- |
| Hermes 版本 | 0.21.0，提交 `693641aa8b4359c602283bdbbc14041e03bc47bc` |
| Hermes 源码 | `/home/ubuntu/haudi-hermes/source` |
| Hermes 配置与会话 | `/home/ubuntu/haudi-hermes/state` |
| Agent 默认工作目录 | `/home/ubuntu/haudi-hermes/workspace` |
| Python 与运行工具 | `/home/ubuntu/haudi-hermes/venv`、`runtime` |
| Open WebUI 配置与数据 | `/home/ubuntu/haudi-hermes/openwebui` |
| Open WebUI 聊天与账号数据库 | `openwebui/data`（容器外持久化） |
| Open WebUI 固定镜像 ID | `openwebui/image.txt` |
| 原生 dashboard | 原服务 `haudi-hermes.service` 保留，可用于回退 |

采用官方 `main-slim` 镜像并固定实际镜像 ID，关闭嵌入模型自动下载及自动标题、标签、后续问题生成。
当前 Open WebUI 为 0.11.3。文档检索使用持久目录中的 `intfloat/multilingual-e5-small`，固定模型版本、查询和内容前缀见 `configs/workstation/retrieval.json`；不依赖额外的付费嵌入接口。普通文字聊天通过 Hermes API。
浏览器使用 Chromium 152、独立共享库和专用 AppArmor 配置，保留 Chromium 沙箱。

## 服务管理

科研扩展由 `deploy-extensions.py` 管理，入口 `deploy-extensions.sh`。已接入论文 MCP、文献检索 Skill 和引用插件；打包、部署、验证和回退步骤见 [MCP 接入教程](../../docs/development/MCP-INTEGRATION.md)。stdio MCP 不监听新端口，随 Hermes 服务管理。另两份教程为 [Skill](../../docs/development/SKILL-INTEGRATION.md) 与 [插件](../../docs/development/PLUGIN-INTEGRATION.md)。

已验证首页、健康检查、管理员登录、Hermes 模型列表，以及浏览器中的中文聊天页和默认模型选择。
切换后 Open WebUI 约占 701 MiB 内存，服务器约有 2.1 GiB 可用内存。原 dashboard 已停止并取消开机启动。

在服务器终端执行：

```bash
sudo docker ps --filter name=haudi-openwebui
sudo docker logs --tail 100 haudi-openwebui
sudo docker restart haudi-openwebui
sudo systemctl status haudi-hermes-api.service
sudo systemctl restart haudi-hermes-api.service
sudo journalctl -u haudi-hermes-api.service -n 100 --no-pager
```

Open WebUI 容器自动重启，Hermes API 开机启动。备份时同时保存 `state` 和 `openwebui`；这些目录含私密凭据。

## 部署脚本

- `setup-api.sh`、`fix-api.sh`、`enable-api-browser.sh`：配置 Hermes API 与工具环境。
- `fetch-openwebui-image.py`、`import-openwebui.sh`：从官方仓库下载、校验镜像并离线导入。
- `stage-openwebui.sh`：在 18119 端口准备新界面。
- `bootstrap-openwebui.sh`：初始化管理员、验证 Hermes 模型连接。
- `cutover-openwebui.sh`：验证后切换到 9119，失败时恢复原 dashboard。
- `verify-openwebui.sh`：验证切换后的健康状态、登录、模型发现与资源占用。
- `build-login-copy.py`、`deploy-login-copy.sh`：构建、部署本站账号文案。脚本校验固定的上游镜像和资源结构，升级 Open WebUI 时需重新检查补丁。
- `configure-research-copy.py`：通过配置 API 更新科研任务建议和助手说明，写入工作站名称及 Hermes 身份文件。
- `build-research-copy.py`、`deploy-research-copy.sh`：构建、部署科研工作站文案；更新中文资源及引用它的文件名，避免浏览器继续使用旧缓存。
- `verify-research-copy.sh`：验证工作站配置、六类任务建议、账号登录和 Hermes 实际身份加载流程。
- `apply-workstation-identity.py`、`deploy-workstation-identity.sh`：统一科研助手身份，更新 `research-SOUL.md`、移除运行框架默认介绍中的品牌前缀，并在模型设置中加入每次请求的身份规则；保留其他模型参数和权限。上传最新身份文件和 Python 脚本后，通过 SSH 执行部署脚本。升级执行引擎后须重新核对品牌介绍补丁。
- `verify-workstation-identity.sh`：通过实际聊天接口验证自我介绍、能力介绍和包含旧版回答的对话，会调用模型 API。备份保存在服务器 `openwebui/identity-backup-*`，验证结果为 `openwebui/identity-verification.json`。
- `enable-public-webui.sh`：备份配置及容器，启用公网 9119 并检查健康状态；失败自动回滚。
- `inspect-public-access.sh`：检查监听地址、账号验证设置及主机防火墙。
- `diagnose-llm.sh`：检查模型配置、密钥是否存在及错误标记，不输出凭据。
- `verify-llm-chat.sh`：重启 Hermes 并通过工作站发送一次简短模型连通性测试（会调用模型 API）。

登录文案更新前的容器保留为停止状态的 `haudi-openwebui-before-login-v1`；原镜像 ID 保存在 `openwebui/image-before-login.txt`。
科研文案镜像当前为 `haudi-openwebui:0.11.3-research-v4`：保留工作站名称定制，并修复截图按钮反馈、HTTP 附件入口及捕获失败后的屏幕流释放。原有上游版权和许可声明保留。该部署有 6 个注册账号且关闭自行注册，适用固定版本 LICENSE 第 4(a) 条的 50 人及以下部署品牌修改例外；扩大使用规模前须重新核对适用条件。

v4 更新前的容器为 `haudi-openwebui-before-20260908T041529Z`，检索配置备份在 `openwebui/retrieval-backup-20260908T041251Z`。新部署脚本使用时间戳记录回退容器和镜像，支持后续重复发布。模型文件位于 `openwebui/data/models/multilingual-e5-small`，随数据目录持久保存。具体修复和重建步骤见 [附件功能修复记录](../../docs/development/ATTACHMENT-FIXES.md)。

回退到原 dashboard（保留 Open WebUI 数据）：

```bash
sudo docker stop haudi-openwebui
sudo systemctl enable --now haudi-hermes.service
```

回退后手动访问 http://127.0.0.1:9119/chat ；新的启动脚本检查的是 Open WebUI 健康接口。

服务器有既有 apt 包依赖冲突。本部署使用独立运行环境与 Docker，不执行系统依赖修复或全局升级。

接入方式参考 [Open WebUI 官方 Hermes 指南](https://docs.openwebui.com/getting-started/quick-start/connect-an-agent/hermes-agent/)。
