# 三组新扩展的服务器试用

入口：**https://42.193.15.167**。刷新页面后新建科研任务，让新会话加载更新后的 Skill 和工具清单。

## 可直接尝试

- 文献核对：“请用 arXiv 工具核对 Attention Is All You Need（1706.03762），报告实际核对结果。”
- CFD 示例：“请加载 npy3d-visualization，使用默认合成示例绘制第 0 帧、第 0 通道曲面图；说明这是演示数据。”
- LaTeX：“请检查服务器试用模板 `/home/ubuntu/haudi-hermes/workspace/examples/latex/template.zip`，根据我提供并确认的正文生成 LaTeX 工程，先展示检查结果，等我确认再打包。”

**当前边界：图像和 ZIP 的生成已接通，网页内预览及下载传输尚未接通。** 工具返回服务器文件路径，不是可点击的公网下载地址。LaTeX 插件不编译 PDF；不能把打包成功描述成已编译通过。上传 ZIP 从 WebUI 到 Agent 文件工作区的完整流程也未在此次验收中验证，LaTeX 实测使用服务器模板或直接传入的小型 Base64 ZIP。

## 部署内容

- 三组 MCP：原论文检索、ARS 文献核对、CFD 可视化。
- 两个插件：引用排版、LaTeX 工程。
- 九份可发现的 Skill：原文献检索、四份 ARS、三份 CFD、LaTeX。
- Ubuntu ParaView 5.11 与 python3-paraview；新增 NumPy、Matplotlib 等绘图依赖，保留既有 Python 包版本。
- CFD 示例数据放在 `workspace/examples/cfd`；绘图输出放在 `workspace/artifacts/cfd`，通过 MCP 环境变量配置。

发布包通过 `configs/workstation/extensions.json` 的 `skill_sources` 将扩展内部 Skill 映射到发布包 `skills/`，保留配套 Markdown 参考资料，并把 CFD 工具名称改为实际 MCP 前缀。`merge_config` 展开 MCP 的 `env` 路径占位符。同名 Skill 和插件的备份分别保存在 `previous/skills/`、`previous/plugins/`，避免重部署时目录碰撞。

## 实测证据（2026-09-09）

- 真实 Hermes 工具注册及调用通过，21 个预期工具可见，9 份 Skill 可加载；保留了 Crossref、Europe PMC 的检索／正文回归。
- 通过 HTTPS 工作站调用 DeepSeek V4 Pro，83.5 秒内实际完成 CFD 检视与曲面 PNG、arXiv 文献核对、LaTeX 模型生成／校验／确认打包。此处 LaTeX 使用真实模型，正文仅为合成测试句；临时管理员个人 Key 已清理。
- ParaView 真实读取合成 VTK：861 个点、800 个单元；成功导入 pressure 数组为 41×21 的 X/Y/Q，NaN 比例 0%。
- 本地 21 项扩展回归通过，包括同名 Skill／插件的连续发布回归。此前 LaTeX 三项边界测试通过。
- Semantic Scholar 仍取决于上游配额；此前本地无 Key 调用遇到 HTTP 429，不能保证匿名调用可用。中文文献只验证过英文输入跳过分支。

服务器证据位于 `extensions/verification.json`、`extensions/expanded-chat-verification.json`、`extensions/paraview-verification.json`。发布版本和备份目录以 `extensions/deployment.json` 为准。WebUI 保持 v9，使用本次扩展发布流程更新 Agent 配置，不通过重建 UI 镜像装载 MCP。

最终扩展版本 `b1773f17ec70f3f5`，备份目录 `extensions/backups/20260909T080019963536Z`。真实模型验收脚本源码为 `deploy/hermes/verify-expanded-chat.py`，运行需要服务器已有测试管理员与可用模型 Key；结果不冒充网页文件下载验收。

## 运维

依赖下载曾因默认 Python 源缓慢，使用 `UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple` 重试完成；没有永久修改系统软件源。ParaView 安装前修复了 nftables 与已安装库的版本不匹配，并刷新过期的 apt 索引；未改写防火墙规则。

回滚使用部署记录所指备份：`venv/bin/python deploy-extensions.py --rollback /home/ubuntu/haudi-hermes/extensions/backups/具体目录`。这会恢复配置与管理的 Skill／插件，不卸载新增系统和 Python 依赖，也不删除用户生成的产物。
