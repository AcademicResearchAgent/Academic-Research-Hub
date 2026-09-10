# 研究过程实时显示

工具进度和结果由运行时提取，独立于模型思考流和回答正文，不额外调用 LLM。工作站统一 `/v1/chat/completions` 路径上的各家模型共用这套实现；模型实际调用工具才有记录。

## 数据路径与修改入口

1. Hermes 的 `tool_start_callback` / `tool_complete_callback` 提供调用 ID、工具名称、参数、实际返回值。
2. `overlays/hermes-agent/workstation_activity.py` 生成公开回执，经 `hermes.tool.progress` SSE 发送；按 ID 跟踪耗时和并行调用。
3. `overlays/open-webui/workstation_models/streaming.py` 转成原生 `status` 事件，携带 `action: workstation_tool`、`toolCallId` 和 `activity`。不伪造 OpenAI `tool_calls`，不插入回答正文。
4. 原有 WebUI socket 事件链保存 `statusHistory`；`overlays/open-webui/ResearchActivity.svelte` 按 ID 合并开始／完成事件，默认展开“研究过程”。刷新后从会话恢复；旧对话不追补未保存过的数据。

`activity` 包含 `title`、`detail`、`state`、`elapsed`、`summary` 和 `items`。每个结果项仅有 `title`、`url`、`note`。状态区分 `running`、`completed`、`failed`、`partial`、`interrupted`。没有完成回执时不将调用标为已完成。

## 当前覆盖

| 工具 | 开始显示 | 返回后显示 |
| --- | --- | --- |
| Crossref、Europe PMC 检索 | 数据库、检索式 | 数量、前 10 条题名、年份、DOI、链接、题录／摘要标识 |
| Crossref DOI 查询 | DOI | 对应题录 |
| Europe PMC 正文 | PMCID、起始字符 | 实际片段字符数、正文总字符数、正文节选说明 |
| web_search | 网页搜索、检索式 | 实际返回题名、链接和数量 |
| web_extract | 输入网址 | 各页面字符数或失败、批次成功比例 |
| Skill、工具发现 | 加载／查看动作、名称 | 调用完成状态 |
| 文件、终端、浏览器 | 操作类型及文件名、程序名或网址 | 调用完成／失败状态 |
| 其他插件／MCP | 工具名称 | 通用回执；新工具可增加参数和结果映射 |

“返回文献”不表示已通过真实性核验，“抓取网页”不等于取得论文全文。正文节选不代表已读整篇、图表和补充材料。空结果、错误和部分失败分别显示。

单个工具通常仅提供开始／完成回调：请求发出时显示检索式，接口返回时显示题名。不能在接口返回之前展示命中，也不能推断工具未上报的下载百分比、解析阶段或子代理内部动作。用户停止生成后，工具是否终止由运行时负责；页面只报告未收到回执。

公开字段采用白名单，不透传完整参数、终端输出、文件内容、原始错误和推理。网址去掉用户信息、查询参数和 fragment，以免转发签名凭据；依赖查询参数的链接可能因此不完整。文本长度、结果条数和解包深度有上限。页面以普通文本呈现，链接只允许 HTTP(S)。

`SOUL.md` 要求过程说明默认中文，补充具体发现或调整检索策略的理由，减少空泛播报。这是提示词约定，不保证每次模型输出的语言，不改写历史上下文。

## 测试与发布

修改覆盖层和补丁生成器，运行 `python scripts/render_product_patches.py`，将补丁应用到锁定源码，然后执行：

```powershell
python scripts/prepare_sources.py --check
python -m unittest discover -s tests -p test_workstation_activity.py -v
python -m unittest discover -s tests -p test_workstation_streaming.py -v
node scripts/check_source_patches.mjs
```

前端需完整构建。`scripts/package_model_release.py` 打包前端、匹配后端、Hermes 回执模块及 SOUL。`deploy/hermes/deploy-research-activity.py` 是 **v8 → v9 的一次性升级**：校验镜像和旧文件哈希，离线测试新镜像，备份引擎和 SOUL，切换并健康检查；失败自动恢复。后续发布必须调整基线与版本号。

```powershell
python scripts/package_model_release.py
python deploy/hermes/upload.py .build/model-release.tar.gz /home/ubuntu/haudi-hermes/model-release.tar.gz
python deploy/hermes/upload.py deploy/hermes/deploy-research-activity.py /home/ubuntu/haudi-hermes/deploy-research-activity.py
python deploy/hermes/remote.py deploy/hermes/deploy-research-activity.sh
```

`deploy/hermes/verify-research-activity.py` 使用服务器内的测试管理员及按需临时配置的 Key，检查真实论文检索／正文回执、Articraft 网页检索与提取的可见过程、刷新持久化。浏览器验收要求已登录独立的 `haudi-activity` 浏览器。结束后清理临时 Key 和成功验收创建的聊天；失败遗留聊天按 `activity-browser-` 标记精确定位清理，不访问普通用户聊天。

部署记录：服务器 `openwebui/activity-deployment.json`；验收记录：`openwebui/activity-verification.json`。回退前核对当前镜像，恢复记录所指备份中的路由文件与 SOUL，移除本次新增的 `gateway/workstation_activity.py`，重启 API，并将 UI 切回记录中的旧容器；不要覆盖后续版本。

## 2026-09-09 线上验收

- v9 镜像：`sha256:3bdcf3f6ffcf90fdb8092c4e1ed165424d61dedb3d93d5e939a6000d043a1876`。发布目录 `model-releases/20260909T025701Z`，备份目录 `activity-backups/20260909T025701Z`。
- DeepSeek V4 Pro 真实 HTTPS 请求用时 16.3 秒。第 10.0 秒出现 Europe PMC 检索式，第 11.6 秒收到 DISCOVER-Seq 论文题名与 DOI `10.1038/s41592-023-01840-z`，第 13.4 秒出现正文读取回执：实际 1,000 字符，总正文 60,061 字符。
- 浏览器查询 Articraft 返回 GitHub 项目和 arXiv `2605.15187`，提取 arXiv 摘要页 2,443 字符；页面明确显示这是网页提取，不冒充论文全文。
- 浏览器确认：执行中可见检索式、最终回答之前可见返回结果、完成后可见提取结果、刷新后记录保留。临时 Key 和测试聊天已清理。
- 5 项回执测试、9 项流式测试、16 项模型／凭据回归测试通过；服务器真实 aiohttp 传输测试、14 个组件编译和完整前端构建通过。最终 HTTPS 健康检查 200，API 服务 active。
