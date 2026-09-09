# cfd_npy3d_mcp 部署文档（详细版）

> 适用对象：`cfd_npy3d_mcp`（扩展 MCP server：`npy3d_*` numpy 三维可视化 + `pvdata_*` ParaView 格式三维可视化）
> 部署目标：CodeBuddy / Claude Desktop 等支持 MCP stdio 的客户端
> 最后核对：自测全部通过，与主 `paraview-mcp` 并行无冲突

本文档把扩展包从「零环境」到「客户端里可调用」的每一步写全：
环境要求 → 依赖安装 → 自测 → CodeBuddy 注册 → 客户端验收 → 日常示例 → 升级/卸载 → 故障排查。

---

## 0. 一句话部署流程

```
确认 Python → pip 装依赖 → （可选）确认 pvpython → python server.py --selftest 全绿
→ 把 cfd-npy-3d 条目合并进 .mcp.json → 重启 CodeBuddy → 在对话中看到 7 个工具
```

---

## 1. 部署前置条件

| 项目 | 要求 | 本机示例（已满足） |
|---|---|---|
| 操作系统 | Windows / Linux / macOS | Windows 10/11 |
| Python | ≥ 3.10（`mcp>=1.2`、`numpy`、`matplotlib`、`Pillow` 可安装） | `D:\Anaconda\python.exe`（3.11） |
| ParaView `pvpython` | **仅 `pvdata_*` 需要**；`npy3d_*` 不需要 | `D:\Program Files\ParaView 6.0.1\bin\pvpython.exe` |
| 磁盘 | 包本体 < 1 MB + 演示数据约 20 MB + 产物目录（自定） | 充足 |
| 数据 | `.npy` 数据集（如 `CFD_TEST`）或 ParaView 文件（`.vtu/.ex2/...`） | `g:/mcp-/CFD_TEST` |

> 说明：`pvdata_*` 只用 pvpython **读数据**，绘图（三维点云/动画）仍在普通 Python + matplotlib 完成，**不依赖 OpenGL / 离屏渲染**。

---

## 2. 目录准备（部署位置）

扩展包整体是一个自包含目录，把整个文件夹放到目标位置即可，**不要求放进系统目录**。

```
g:/mcp-/cfd_npy3d_mcp/          ← 部署目录（整包拷贝或原地使用）
├── server.py                   FastMCP server 入口（stdio）※注册时指向它
├── registry.py                 契约加载/校验（读 manifest.json + tools/*.json）
├── handlers.py                 7 个工具实现（显式签名，与契约一一对应）
├── core.py                     X/Y/Q 协议解析 + 曲面/点云/GIF 绘制（执行层）
├── pvbridge.py                 读 config/paraview.json 定位 pvpython + 执行 job
├── pvjob_pvdata.py             pvpython 侧 job 执行器（inspect / points / import2d）
├── manifest.json               工具/技能注册清单（契约索引）
├── tools/                      每个工具一份参数契约 JSON（7 个）
├── checks/                     一致性质量门（check_registry_consistency.py）
├── config/                     ParaView 工作配置（paraview.json / paraview_readers.json）
├── skills/                     SKILL.md 技能描述层（可选，方式 B 注册用）
├── make_sample.py              一键生成演示数据（sample_data）
├── sample_data/                演示数据（缺失时自测会自动生成）
├── requirements.txt            依赖清单
├── mcp.example.json            MCP 注册示例（含可选 PARAVIEW_PVPYTHON）
├── README.md                   能力速览
├── DEPLOY.md                   本文档
├── .run/                       运行时自动创建：pvpython 临时 job/.npz（可随时清空）
└── output/                     ※默认产物根（见 §4 环境变量，可改走 NPY3D_OUT_ROOT）
```

### 2.1 产物目录约定

- 产物根默认 = 工作区 `output`（即 `g:/mcp-/output`），可用环境变量 `NPY3D_OUT_ROOT` 改指任意目录。
- 归档规则与主 MCP 一致：

```
带 case 参数 → <产物根>/cases/<case>/render/<时间戳>.png|.gif
不带 case    → <产物根>/render/<时间戳>.png|.gif
同一秒多次写入自动加 _1/_2 后缀
```

> 部署时确认产物根**可写**（Windows 下避免放在需要管理员权限的系统目录）。

---

## 3. 依赖安装

### 3.1 Python 依赖（npy3d_* 必需，pvdata_* 也需普通 Python 能 import mcp/matplotlib）

```powershell
# 用部署要用的那个 python 装（务必与注册进 MCP 的 command 是同一个）
D:\Anaconda\python.exe -m pip install -r g:\mcp-\cfd_npy3d_mcp\requirements.txt
```

等价手写：

```powershell
D:\Anaconda\python.exe -m pip install "mcp>=1.2.0" "numpy>=1.24" "matplotlib>=3.7" "Pillow>=10.0"
```

验证 import：

```powershell
D:\Anaconda\python.exe -c "import mcp, numpy, matplotlib, PIL; print('deps ok')"
```

### 3.2 ParaView（仅 pvdata_* 需要）

- 已安装 ParaView 即可，无需任何 pip 包。
- 桥**优先读本扩展包 `config/paraview.json`**（`pvpython.candidates`，支持 `${VAR}` 展开与 glob），
  其后追加环境变量 / PATH 兜底，最后是内置常见路径：

```
1. config/paraview.json -> pvpython.candidates   （推荐在此配置；见 §3.3）
2. 环境变量 PARAVIEW_PVPYTHON
3. 环境变量 PARAVIEW_BIN\pvpython.exe
4. PATH 里的 pvpython（shutil.which）
5. 内置常见路径 D:\Program Files\ParaView 6.0.1\bin\pvpython.exe
```

- 验证：

```powershell
Test-Path "D:\Program Files\ParaView 6.0.1\bin\pvpython.exe"
# True 即可；找不到就在 config/paraview.json 里补候选路径（见 §3.3）
```

### 3.3 ParaView 集中配置（config/paraview.json）

扩展包自带 `config/paraview.json`，集中管理 pvpython 定位与 job 超时，无需改代码：

```json
{
  "pvpython": {
    "candidates": [
      "${PARAVIEW_PVPYTHON}",
      "D:/Program Files/ParaView 6.0.1/bin/pvpython.exe"
    ],
    "job_timeout_seconds": 600
  }
}
```

- `pvpython.candidates`：按顺序取第一个存在者；支持 `${VAR}` 环境变量展开与 `*`/`?` glob。
- `config/paraview_readers.json`：由 `checks/export_paraview_readers.py` 枚举生成，
  记录 ParaView 支持的 reader 类名与常见扩展名映射，供 `pvdata_import` 技能引用。

- ParaView 自带示例数据 `examples\disk_out_ref.ex2` 可作为 `pvdata_*` 的验收数据（见 §7）。

---

## 4. 环境变量一览

| 变量 | 必填 | 作用 | 示例 |
|---|---|---|---|
| `NPY3D_OUT_ROOT` | 否 | 产物根目录；缺省 `<server.py 上级>/output` | `g:/mcp-/output` |
| `PARAVIEW_PVPYTHON` | `pvdata_*` 建议 | `pvpython.exe` 绝对路径 | `D:/Program Files/ParaView 6.0.1/bin/pvpython.exe` |
| `PARAVIEW_BIN` | 否 | 备选查找路径（`<PARAVIEW_BIN>/pvpython.exe`） | `D:/Program Files/ParaView 6.0.1/bin` |

> 这些变量既可设成**系统环境变量**，也可写在 MCP 配置的 `env` 里（见 §5），推荐后者——只影响该 MCP server。
> 对于 ParaView 定位，**更推荐在扩展包 `config/paraview.json`（§3.3）里配置**——无需每次重开 IDE 都保证 env 存在。

---

## 5. 注册到 CodeBuddy

### 5.1 方案 A：项目级 `.mcp.json`（推荐，随仓库走）

CodeBuddy 支持项目根目录的 `.mcp.json`。本工作区已存在该文件（内含主 `paraview-mcp`），把 `cfd-npy-3d` 条目**合并**进去：

文件：`g:\mcp-\.mcp.json`

```json
{
  "mcpServers": {
    "paraview-mcp": {
      "command": "D:\\Anaconda\\python.exe",
      "args": ["g:\\mcp-\\mcp_server.py"],
      "env": {
        "PARAVIEW_PVPYTHON": "D:\\Program Files\\ParaView 6.0.1\\bin\\pvpython.exe"
      }
    },
    "cfd-npy-3d": {
      "command": "D:\\Anaconda\\python.exe",
      "args": ["g:\\mcp-\\cfd_npy3d_mcp\\server.py"],
      "env": {
        "NPY3D_OUT_ROOT": "g:/mcp-/output",
        "PARAVIEW_PVPYTHON": "D:/Program Files/ParaView 6.0.1/bin/pvpython.exe"
      }
    }
  }
}
```

要点：

- `command`/`args` 里的 **Python 必须是装了依赖的那个**（§3.1），`args[0]` 指向 `server.py` 绝对路径。
- Windows JSON 里反斜杠要写成 `\\`；也可以全用正斜杠 `g:/mcp-/...`（server 内部路径处理兼容）。
- 只跑 `npy3d_*`（`.npy`）时 `PARAVIEW_PVPYTHON` 可省略；要用 `pvdata_*` 建议显式写。
- 若 `NPY3D_OUT_ROOT` 不写，产物落在 `g:/mcp-/output`，效果相同。

### 5.2 方案 B：用户级配置（对所有项目生效）

文件：`~/.codebuddy/.mcp.json`（推荐；不存在则创建，内容同 §5.1 的 `mcpServers` 片段，去掉与项目无关的旧条目即可）

```powershell
notepad $env:USERPROFILE\.codebuddy\.mcp.json
```

> 作用域优先级 `local > project > user`，同名 server 就近生效。

### 5.3 方案 C：CLI 一键添加

```powershell
# 若装了 codebuddy CLI，可用（需换成正斜杠/转义后的真实路径）
codebuddy mcp add --scope project cfd-npy-3d -- "D:/Anaconda/python.exe" "g:/mcp-/cfd_npy3d_mcp/server.py"
```

带环境变量建议仍用手改 JSON（§5.1/5.2）。

### 5.4 生效与验收

1. **重启 CodeBuddy**（或让 MCP 连接重新加载）。
2. `project` 作用域的 server 首次连接需在弹窗里**批准**。
3. 在会话里输入 `/mcp` 查看服务器状态与诊断。
4. 对话中应能看到 7 个工具；工具全名 `mcp__cfd-npy-3d__npy3d_inspect` 等。若工具不可用，检查权限设置（allow/ask/deny），并在 `/mcp` 里确认 server 已 connected。

### 5.5 方式 B：skill 技能发现（可选，与 5.1~5.4 二选一）

不需要 MCP 注册时，可把技能描述层交给支持 agent skills 的客户端：

- 复制/软链 `skills/npy3d_visualization`、`skills/pvdata_visualization`、`skills/pvdata_import` 到客户端技能目录（Claude Code：项目 `.claude/skills/`）。
- agent 通过 `SKILL.md` 的 frontmatter（name/description）自行判断何时使用并按其流程调用工具——此方式下工具仍需以 MCP（§5.1~5.4）方式注册才能被调用，SKILL.md 只是「使用说明书」；若客户端能原生执行脚本则可不注册 MCP。

---

## 6. 注册到 Claude Desktop / Claude Code（可选）

Claude Desktop 配置文件 `%APPDATA%\Claude\claude_desktop_config.json`，往 `mcpServers` 加同名字段即可（内容同 §5.1 的 `cfd-npy-3d` 条目），保存后重启 Claude Desktop。

Claude Code 的项目级配置 `<项目>/.mcp.json` 写法相同。

---

## 7. 部署后验收清单（照抄即可）

### 7.1 无客户端自测（部署完成后第一件事）

```powershell
D:\Anaconda\python.exe g:\mcp-\cfd_npy3d_mcp\server.py --selftest
```

期望输出链路（任一步失败会打印 `SELFTEST FAILED: <原因>`）：

| 阶段 | 输出标志 | 说明 |
|---|---|---|
| 0 | `check ok` / `RESULT: PASS` | 一致性质量门：manifest↔tools↔handlers↔skills（v1.2 起） |
| 1 | `inspect ... T=48 C=5 HxW=81x201` | 演示数据（缺失会自动 `make_sample` 生成） |
| 2 | `surface ok -> npy3d_surface_*.png` | 单通道曲面 PNG |
| 2 | `surface(all) ok -> ...` | 全通道并排 PNG |
| 3 | `animation ok -> npy3d_anim_*.gif` | 时间 GIF |
| 4 | `real CFD_TEST ok: T=2490 ...` | 仅当 `g:/mcp-/CFD_TEST` 存在 |
| 5 | `pvdata inspect/scatter3d/animation ok` | 仅当 pvpython 可用且找到 `disk_out_ref.ex2` |
| 5 | `pvdata import2d ok` + `import2d -> render_surface ok` | 仅当 pvpython 可用；样本 `plane2d.vtk` 由 `make_sample.py` 自动生成 |
| 末 | `ALL SELFTEST STEPS OK` | 全绿 |

产物在 `g:/mcp-/output/cases/cfd_npy3d_selftest/render/` 下，打开 PNG 目检：翼型/圆柱附近的 3D 曲面与颜色分布应连续、无 NaN 空洞。

### 7.2 客户端内验收

在 CodeBuddy 对话里依次问：

1. `npy3d_inspect(data_dir="g:/mcp-/cfd_npy3d_mcp/sample_data")` → 返回 T/C/H×W 与各通道统计。
2. `npy3d_render_surface(data_dir="g:/mcp-/CFD_TEST", frame=0, channels="0", case="deploy_check")` → 返回 PNG 路径，打开看图。
3. 若要用 ParaView 格式：
   `pvdata_inspect(file_path="D:/Program Files/ParaView 6.0.1/examples/disk_out_ref.ex2")`
   → 返回 reader/点数/数组；再 `pvdata_render_scatter3d(file_path=..., array_name="Temp", case="deploy_check")` → 出点云 PNG。

全部返回正常路径且图片可打开即部署成功。

---

## 8. 日常使用示例

```text
# .npy 三维曲面（真实 CFD_TEST）
npy3d_render_surface(data_dir="g:/mcp-/CFD_TEST", frame=0, channels="0", case="naca_cylinder")

# .npy 时间动画
npy3d_render_animation(data_dir="g:/mcp-/CFD_TEST", channel=0, max_frames=48, fps=6, case="naca_cylinder")

# ParaView 文件检视（先检视再定 array/时间步，避免瞎猜）
pvdata_inspect(file_path="E:/sim/case.vtu")

# ParaView 文件三维点云着色（不指定 array 自动选首个标量）
pvdata_render_scatter3d(file_path="E:/sim/case.vtu", array_name="pressure", timestep_index=0, case="sim1")

# ParaView 时变文件动画（时间步很多时先 inspect 看步数）
pvdata_render_animation(file_path="E:/sim/case.pvd", array_name="velocity", max_frames=24, fps=6, case="sim1")
```

---

## 9. 升级 / 重装 / 卸载

| 操作 | 做法 |
|---|---|
| 升级（覆盖新版本包） | 备份自定义产物后整目录替换 `cfd_npy3d_mcp`；随后重跑 `--selftest`。配置无需改（路径不变时）。 |
| 只清临时文件 | 删 `.run/` 里的 `*.npz/*.json`（server 会自动重建；不影响任何功能） |
| 重新生成演示数据 | `python make_sample.py`（或删掉 `sample_data/*.npy` 后跑 `--selftest` 自动补） |
| 卸载（停用） | 从 `.mcp.json` / `~/.codebuddy/.mcp.json` 移除 `cfd-npy-3d` 条目 → 重启客户端。产物目录可自行删除。 |
| 换 Python / ParaView 路径 | 只改 MCP 配置里的 `command` 与 `env.PARAVIEW_PVPYTHON`，无需改扩展包代码。 |

---

## 10. 故障排查

| 症状 | 原因 | 处理 |
|---|---|---|
| `--selftest` 报 `No module named 'mcp'/'numpy'/'matplotlib'` | 用了错误的 Python 装依赖 | 用注册时同一个 python 执行 §3.1 |
| server 启动即退出 / 工具不出现 | `command` 指向的 Python 不对、依赖没装、`args` 路径错误 | 先在终端手动 `python <server.py>` 看是否报错；再核对 §5.1 JSON 路径转义 |
| `/mcp` 显示 server 存在但工具不可用 | project 级未批准 / 工具权限 deny | 重启后在弹窗批准；检查工具权限 allow/ask |
| `pvdata_*` 报 `pvpython.exe not found` | 桥没找到 pvpython | 设 `env.PARAVIEW_PVPYTHON`（§4/§5.1）后重启 |
| `pvpython job failed` + 尾部输出是文件读取错误 | 文件格式不被 reader 自动识别 / 路径带空格且被拆 | 确认文件存在、扩展名常见；路径加引号或换正斜杠 |
| `npy3d_*` 报 shape 不匹配 | Q 布局与 X/Y 网格对不上 | 先 `npy3d_inspect` 看推断结果，确认是否 `(T,C,H,W)` 等 |
| 动画报“抽样帧含 NaN” | 抽到的帧该通道有 NaN | 换通道/减小 max_frames 避开坏帧，或换数据段 |
| `pvdata_render_animation` 帧与帧一样 | 该文件本身静态/单时间步 | 属正常；`pvdata_inspect` 看 timesteps 确认 |
| 图片里中文变方块 | （历史问题） | 图内文字已全英文，md 文本是 UTF-8 不受影响；确认控制台 `chcp 65001` 后再跑自测 |
| 找不到 ParaView 示例 ex2 | 安装目录无 examples | 不影响 `npy3d_*`；pvdata 自测会跳过该步 |
| 产物没写进预期目录 | 未设 `NPY3D_OUT_ROOT`，或指向了不可写路径 | 设 `NPY3D_OUT_ROOT`（§4）；检查目录权限 |

---

## 11. 安全与注意事项

- 该 server 只做**本地文件读取 + 绘图**，不监听端口、不访问网络、不写系统目录。
- `env` 里不要硬编码密钥类敏感信息；本扩展无需任何密钥。
- 大 `.npy`（1 GB 级）按 `mmap` 流式读，`pvdata_*` 大数据按 `max_points` 子采样，一般不会 OOM；但超大时仍建议先 `inspect`。
- 首次调用 `pvdata_*` 会启动一次 pvpython，耗时数秒属正常。
