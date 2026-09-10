# 新扩展本地试用

2026-09-09 已合并 PR #3、#4、#5，本地主分支同步到 `d13bb8d2f1028bb9068b34cfba5f81e7e0ae011c`。合并时保留了 LaTeX、ARS、CFD 的全部注册项，依赖安装使用遍历各 MCP 的通用实现。

## 重复运行

在仓库根目录使用已安装 MCP、NumPy、Matplotlib、Pillow、httpx 和 PyYAML 的 Python：

```powershell
python -m unittest discover -s tests -p test_extensions.py -v
python -m unittest discover -s tests -p test_latex_plugin.py -v
python scripts/try_extensions.py
```

最后一条命令真实启动三个本地 stdio MCP 服务，完成协议初始化和工具发现，生成小规模合成 CFD 数据并调用检视、曲面 PNG、GIF 动画工具，不访问文献网站。加 `--online` 时额外调用 arXiv、OpenAlex、Semantic Scholar 的公开文献核对接口：

```powershell
python scripts/try_extensions.py --online
```

产物集中在 `.build/local-extension-trial/`：

- `report.json`：实际调用结果与可用性。
- `cfd/cases/synthetic_trial/render/`：PNG 和 GIF，均为合成示例，不是科研实验结果。
- `mcp.json`：当前电脑 Python 路径对应的三组 MCP stdio 配置，可用于支持该配置格式的本地 MCP 客户端；这是生成文件，换电脑后重新生成。
- `synthetic-data/`：本次试用的 X/Y/Q NumPy 数据及平面 VTK 样例。

新环境建议先在仓库内建立独立虚拟环境，再按 `extensions/mcp/*/requirements.txt` 安装依赖；不要复制生产密钥或运行 Linux 服务器发布脚本来配置 Windows。本地试用不启动完整聊天网页，LaTeX 插件仍需 Hermes 的插件加载与 LLM 上下文才能由 Agent 实际生成论文。

## 本次结果与边界

| 范围 | 实测结果 |
| --- | --- |
| 扩展与 LaTeX 行为测试 | 23 项通过；LaTeX 生成使用固定的测试模型输出，验证 ZIP 检查、工程生成、引用检查、确认及打包 |
| MCP 协议 | paper-search 4 个、ars-resolvers 4 个、cfd-npy3d 7 个工具成功发现 |
| CFD NumPy 数据 | 检视、曲面 PNG、4 帧 GIF 均通过真实 MCP 调用生成 |
| arXiv | `1706.03762` / Attention Is All You Need 核对成功 |
| OpenAlex | `10.1038/s41592-023-01840-z` / DISCOVER-Seq 论文核对成功 |
| Semantic Scholar | 重试后仍 HTTP 429，返回 `degraded: true`，不视作查无文献 |
| 中文文献接口 | 仅验证英文输入的跳过分支，未实测中文来源联网核对 |
| ParaView | 本机未找到 pvpython，相关 pvdata 导入和渲染未实测 |

需要 ParaView 时，安装后设置 `PARAVIEW_PVPYTHON` 为实际 `pvpython.exe` 路径，具体操作见 [ParaView 接入说明](PARAVIEW-INTEGRATION.md)。ARS 当前这四个工具以已有题名／DOI 为输入进行文献核对，不等同于通用主题检索接口。

此次拉取前的本地未提交工作已恢复，备份仍保存在 Git stash，说明为 `Preserve local workstation v9 work before merging PRs 3 4 5`。确认后再自行清理该备份，勿重复 apply。
