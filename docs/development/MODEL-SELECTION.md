# 模型目录与个人 API Key

目录由 `configs/workstation/model-catalog.json` 管理，2026-09-08 核对了 Qwen、Kimi、DeepSeek、GLM 的当前模型。目录包含旗舰、快速和实验视觉型号，界面明确标记实验版本。模型可用性取决于厂商区域、账号授权和额度；展示目录不表示本站提供这些模型的免费额度。

## 使用流程

点击聊天顶部的模型名称，首次选择某厂商模型时弹出配置窗口。选择厂商接入区域，填写自己的 API Key，验证成功后才切换模型。验证发送一条短消息，会使用厂商少量额度；余额不足、Key 错误、区域或权限不符会显示错误并保留原选择。

同一账号同一厂商复用已配置的 Key，首次切换到该厂商的另一模型时仍会验证模型权限。顶部“模型密钥”可更换或删除自己的密钥。更换失败保留旧密钥；删除影响当前账号此厂商所有区域，不影响其他账号。每个厂商当前只有一个活动区域，再次填写其他区域的 Key 会切换活动区域。

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

修改目录、`overlays/open-webui/ModelKeyDialog.svelte`、`overlays/open-webui/workstation_models/` 或 `overlays/hermes-agent/workstation_runtime.py`。按开发指南先反向应用旧补丁，再运行 `render_product_patches.py` 和 `prepare_sources.py`。不要直接覆盖尚未导出的源码修改。

```powershell
python -m unittest discover -s tests -p "test_workstation*.py" -v
# 在 reference/open-webui 内，Node.js 22：
npm ci --force --ignore-scripts --no-audit --no-fund
$env:NODE_OPTIONS='--max-old-space-size=8192'
npm run build
# 返回根目录：
python scripts/package_model_release.py
```

完整前端构建产物和对应 Python 源码打包为 `.build/model-release.tar.gz`，排除源码映射、凭据和用户数据。上传到部署根目录后运行 `build-model-release.sh`，先构建 v5 镜像并在无网络、无生产数据的容器中跑测试。测试通过后 `deploy-model-runtime.py` 检查运行源码校验值、备份并更新 Agent；健康检查失败自动恢复。UI 使用现有 `deploy-research-copy.sh` 更新，保留旧容器并在健康检查失败时回退。最后运行 `configure-model-catalog.py` 注册目录，沿用默认模型的访问权限。

上游全仓 Svelte 类型检查目前有大量存量错误，不能将完整构建通过描述为全仓类型检查通过。

## 本次验收（2026-09-08）

v5 已部署到服务器。Node.js 22 完整生产构建、9 个修改组件编译、13 项密钥与路由测试、4 项截图行为测试通过；服务器隔离容器额外通过 12 项密钥测试。新增窗口没有 Svelte 类型诊断，全仓检查仍有 7,789 项存量诊断和 202 项警告。

真实 DeepSeek Key 的保存验证成功，Flash 与 Pro 分别完成流式回复，查询仅本次测试会话的数据库记录确认执行型号与所选型号一致；测试 Key 随后删除。浏览器确认目录显示、首次 Qwen 配置、无效 Key 错误和取消保留原选择。升级后的上传、中文向量检索、公开网页索引及回答引用回归通过。

Qwen、Kimi、GLM 尚未使用有效付费 Key 完成真实对话验收；会在用户首次填写时向对应厂商验证。不能将目录展示、无效 Key 检查或模拟测试当成这些厂商的完整实测结果。HTTPS 上线后已再次验证个人 Key 保存及 DeepSeek 两个型号的流式回复，详见 [HTTPS 运维说明](HTTPS.md)。

## 厂商依据

- [阿里云模型列表](https://www.alibabacloud.com/help/en/model-studio/models)与[兼容接口](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)：Qwen3.8 系列及区域接口。
- [Kimi 模型目录](https://platform.kimi.com/docs/models)：Kimi K3、K2.7 Code；已退役的 K2.5 不列入。
- [DeepSeek API 文档](https://api-docs.deepseek.com/)：V4 Pro、Flash 与实验视觉版本。
- [GLM 官方源码说明](https://github.com/zai-org/GLM-5/blob/main/README.md)与[智谱模型文档](https://docs.bigmodel.cn/cn/guide/models/text/glm-5.2)：GLM-5.3、Flash、5.2。

新增厂商应同时补充官方域名白名单、模型 ID、区域及密钥入口；不要仅在 UI 写一个展示名。更新目录需同步发布 UI 后端和 Agent 端，以免两端白名单不一致。
