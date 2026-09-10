# 模型目录与个人 API Key

目录由 `configs/workstation/model-catalog.json` 管理，2026-09-08 核对了 Qwen、Kimi、DeepSeek、GLM 的当前模型。当前共 9 款，已移除 DeepSeek V4 Flash Vision 实验版，保留普通 Flash。页面名称“Kimi K2.7”是工作站简称，实际仍调用官方列出的 `kimi-k2.7-code`，并未配置不存在的 `kimi-k2.7` 接口。模型可用性取决于厂商区域、账号授权和额度。

## 使用流程

点击聊天顶部的模型名称，首次选择某厂商模型时弹出配置窗口。选择厂商接入区域，填写自己的 API Key，验证成功后才切换模型。验证发送一条短消息，会使用厂商少量额度；余额不足、Key 错误、区域或权限不符会显示错误并保留原选择。

同一账号同一厂商复用已配置的 Key，每个型号分别检测权限。顶部“模型密钥”可更换或删除自己的密钥。更换失败保留旧密钥；删除影响当前账号此厂商所有区域，不影响其他账号。每个厂商当前只有一个活动区域，再次填写其他区域的 Key 会切换活动区域。

打开模型选择器或密钥配置窗口时自动加载各型号的状态，并对已配置、缓存过期的型号发送简短测试请求：

| 状态 | 含义 |
| --- | --- |
| 未配置 | 当前账号没有该厂商的活动 Key，不发送厂商请求 |
| 可用 | 此 Key 在当前区域对该型号的短请求通过 |
| 不可用 | 实测失败，悬停状态可见权限、余额、限流或连接错误说明 |
| 检测中… | 临时状态，等待服务器完成检测 |
| 检测失败 | 工作站检测接口自身失败，不能据此判断厂商模型不可用 |

成功结果缓存 5 分钟，失败结果缓存 1 分钟。缓存按账号、厂商、具体型号、区域与密钥指纹分开，在服务重启后清空；更换和删除 Key 会失效对应缓存。相同检测合并，单进程同时最多 3 个厂商请求，每账号每分钟最多 18 个新检测。选择模型时复用有效结果或重新检测，不再把历史一次验证通过视为永久可用。检测会使用少量 API 额度，不调用 Agent 工具、不发送聊天或科研材料，也不代表长任务、工具或图像能力全部验收通过。

选择行保留模型名称与状态，移除原来的标签、连接类型和说明图标；密钥窗口仍保留接入区域和错误说明，帮助配置。

新会话默认选择：按当前可见模型列表的顺序，跳过未配置和不可用项，必要时检测尚未确认的型号，选中第一个可用型号；不沿用上一会话、个人固定默认或分组默认。结果复用同一套可用性缓存。检测期间显示提示，用户手动选择会取消自动选择；没有可用模型时保持未选择并提示配置密钥。历史会话继续使用原来的模型，明确带 `model` / `models` 参数的链接仍按显式选择处理。研究笔记内的新会话也使用该规则。

默认选择实现为 `overlays/open-webui/DefaultModel.js`，通过源码补丁接入 `Chat.svelte` 的新会话入口，保护路由切换和手动选择，避免迟到的检测结果覆盖当前会话。行为测试运行 `node --test tests/default-model.test.mjs`。

选择列表只显示具名模型，原来使用服务器统一 Key 的“科研助手”入口已隐藏。默认显示 DeepSeek V4 Flash，仍需配置个人 Key；不会回退到统一模型。基础记录使用 `meta.hidden=true`，内部连接仍保持活动，供其他型号调用与权限检查使用；已有聊天记录不改写。关闭自动随机选模型的 Arena 入口；原设置备份在服务器 `openwebui/model-catalog-backup/`。

用户直接访问 **https://42.193.15.167**，即可在网页中填写 API Key。服务器使用受信任的 IP 证书并自动续期，原 HTTP 80 / 9119 入口自动跳转 HTTPS，日常使用无需 SSH。

以下仅作为有服务器权限的开发者排障入口，通信通过 SSH 加密：

```powershell
ssh -N -L 127.0.0.1:19119:127.0.0.1:9119 haudi-hermes-server
```

此方式依赖运维配置的 SSH 别名。其他同事应使用工作站正式 HTTPS 入口，不能为配置模型共享 SSH 私钥。

本仓库的 Windows 辅助脚本 `scripts/start_secure_access.ps1` 会在后台建立同一隧道，校验固定服务器主机密钥，只监听本机回环地址。SSH 进程退出后可重新运行脚本。

## 实现边界

- UI 的 `workstation_models` 模块提供认证后的目录、保存、验证、删除接口，用户身份来自登录令牌，客户端不能指定他人账号。
- `workstation-credentials.db` 与账号数据库同处持久数据卷。Fernet 加密密钥从稳定的 `WEBUI_SECRET_KEY` 派生；备份时必须同时保管该秘密，丢失后需要用户重新录入 Key。禁止将数据卷、环境文件或密钥提交 Git。
- 聊天桥接只转发允许字段。模型、官方端点和个人密钥放入 120 秒有效的加密认证封装，Hermes 使用内部服务密钥解封并再次核验目录和会话范围。
- 账号、模型和聊天 ID 共同决定会话范围，显式个人路由覆盖全局配置，禁用默认模型回退。密钥不写入模型配置、前端存储或聊天消息。
- 密钥隔离并不等于 Agent 文件系统多租户隔离；现有 Agent 工作目录仍共享。厂商模型原生视觉能力和工作站工具链实际支持程度需要分别验收。

## 开发与发布

修改目录、`overlays/open-webui/ModelKeyDialog.svelte`、`ModelAvailability.ts`、`workstation_models/` 或 `overlays/hermes-agent/workstation_runtime.py`。可用性调度与缓存位于 `workstation_models/availability.py`，认证和厂商请求位于 `router.py`，行内标注通过补丁生成器修改 `ModelItem.svelte`。按开发指南先反向应用旧补丁，再运行 `render_product_patches.py` 和 `prepare_sources.py`。不要直接覆盖尚未导出的源码修改。

```powershell
python -m unittest discover -s tests -p "test_workstation*.py" -v
# 在 reference/open-webui 内，Node.js 22：
npm ci --force --ignore-scripts --no-audit --no-fund
$env:NODE_OPTIONS='--max-old-space-size=8192'
npm run build
# 返回根目录：
python scripts/package_model_release.py
```

完整前端构建产物和对应 Python 源码打包为 `.build/model-release.tar.gz`，排除源码映射、凭据和用户数据。`build-model-release.sh`、`deploy-model-runtime.py` 是历史 v5 发布入口，不用于覆盖后续版本。

本次 v6 → v7 使用 `deploy/hermes/deploy-model-status.py`：上传发布包与该脚本，在服务器部署根目录执行 `venv/bin/python deploy-model-status.py`。它核对固定 v6 镜像，构建完整 v7 前端和后端并在隔离容器跑测试，再备份旧容器、两个目录文件和模型记录，切换后同步模型名称、停用实验型号；发生异常自动恢复。脚本不替换 Hermes 的思考流补丁。已是 v7 时不应重复执行 v6 升级脚本。

部署记录在服务器 `openwebui/model-status-deployment.json`，其中包含发布目录、备份路径、旧容器和包哈希。备份的 `models.json` 保存被修改的模型记录；手动回退需同时恢复两个目录文件、旧容器及这些记录，不能只改镜像标签。通用 `configure-model-catalog.py` 已识别目录中的 `retired_models`，后续注册也会隐藏并停用已移除型号。

`verify-model-status.py` 验证 DeepSeek Flash / Pro 的真实可用状态、缓存复用、目录变更，以及失效密钥的不可用状态。失效密钥用管理员账号的临时测试条目模拟，其他账号和既有个人密钥不覆盖，结束后清理；不会绕过正式密钥保存接口的验证。可选浏览器参数必须来自当前空白测试页面的实际 DOM 引用。

新会话默认规则的 v7 → v8 发布入口为 `deploy/hermes/deploy-default-model.py`。它核对固定 v7 镜像，只替换完整前端产物；账号数据库、可用性检测后端和 Hermes 保持原配置。使用同一 `package_model_release.py` 打包并上传，核对传输哈希后在服务器执行 `venv/bin/python deploy-default-model.py`。部署记录为 `openwebui/default-model-deployment.json`，失败自动恢复旧容器；已经是 v8 时不应重复运行此升级入口。

`verify-default-model.py` 在已登录的 `haudi-default-model` 专用测试浏览器中验证列表顺序、手动切换后新开会话、历史会话模型保留和无可用模型提示。使用无个人密钥的测试管理员，临时配置服务器既有 DeepSeek Key，结束后清理 Key 和仅本次创建的历史会话测试记录。验收结果写入 `openwebui/default-model-verification.json`。

上游全仓 Svelte 类型检查目前有大量存量错误，不能将完整构建通过描述为全仓类型检查通过。

## 本次验收（2026-09-08）

v8 已部署，镜像 `sha256:4d985c52e1b09c9574a16ec876ada7a35cbfba5312231618313562fc3883e6ab`。5 项默认选择行为测试、修改组件编译和 Node.js 22 完整前端构建通过。HTTPS 浏览器确认：先验证 Flash 的 Key 后，新会话仍选择列表更靠前的 Pro；手动切到 Flash 再开新会话仍选择 Pro；已有 Flash 会话保持原模型；删除临时 Key 后，新会话保持未选择并提示无可用模型。测试 Key 和历史会话夹具已清理。发布目录为 `model-releases/20260908T094952Z`，旧容器为 `haudi-openwebui-before-default-model-20260908T094952Z`。

v7 已部署，镜像 `sha256:5cf0afa93bb42dbf92c7d9b9b4b04ff4d001b1badee11e409dcf0812b3cb0b8c`。Node.js 22 完整生产构建及服务器隔离容器的 26 项测试通过，包含模型与凭据、并发检测及此前思考流的回归检查。生产 HTTPS 下，DeepSeek Flash / Pro 的可用状态和缓存复用通过；临时失效 GLM Key 正确得到不可用状态，这不是对 GLM 服务或有效 Key 的不可用判断。浏览器中三种状态、9 款目录、Kimi 简称和实验型号移除均通过，临时个人测试 Key 已删除。

发布目录为 `model-releases/20260908T085912Z`，备份为 `model-status-backups/20260908T085912Z`，旧容器为 `haudi-openwebui-before-model-status-20260908T085912Z`，验收记录为 `openwebui/model-status-verification.json`。

v5 已部署到服务器。Node.js 22 完整生产构建、9 个修改组件编译、13 项密钥与路由测试、4 项截图行为测试通过；服务器隔离容器额外通过 12 项密钥测试。新增窗口没有 Svelte 类型诊断，全仓检查仍有 7,789 项存量诊断和 202 项警告。

真实 DeepSeek Key 的保存验证成功，Flash 与 Pro 分别完成流式回复，查询仅本次测试会话的数据库记录确认执行型号与所选型号一致；测试 Key 随后删除。浏览器确认目录显示、首次 Qwen 配置、无效 Key 错误和取消保留原选择。升级后的上传、中文向量检索、公开网页索引及回答引用回归通过。

Qwen、Kimi、GLM 尚未使用有效付费 Key 完成真实对话验收；会在用户首次填写时向对应厂商验证。不能将目录展示、无效 Key 检查或模拟测试当成这些厂商的完整实测结果。HTTPS 上线后已再次验证个人 Key 保存及 DeepSeek 两个型号的流式回复，详见 [HTTPS 运维说明](HTTPS.md)。

## 厂商依据

- [阿里云模型列表](https://www.alibabacloud.com/help/en/model-studio/models)与[兼容接口](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)：Qwen3.8 系列及区域接口。
- [Kimi 模型目录](https://platform.kimi.com/docs/models)：Kimi K3、K2.7 Code；已退役的 K2.5 不列入。
- [DeepSeek API 文档](https://api-docs.deepseek.com/)：V4 Pro、Flash 与实验视觉版本。
- [GLM 官方源码说明](https://github.com/zai-org/GLM-5/blob/main/README.md)与[智谱模型文档](https://docs.bigmodel.cn/cn/guide/models/text/glm-5.2)：GLM-5.3、Flash、5.2。

新增厂商应同时补充官方域名白名单、模型 ID、区域及密钥入口；不要仅在 UI 写一个展示名。更新目录需同步发布 UI 后端和 Agent 端，以免两端白名单不一致。
