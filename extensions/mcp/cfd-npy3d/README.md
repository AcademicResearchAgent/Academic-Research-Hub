# cfd_npy3d_mcp —— 扩展 MCP 工具：numpy + ParaView CFD 数据三维可视化

> 📖 **详细部署（环境要求 / 依赖安装 / CodeBuddy 注册 / 验收清单 / 故障排查）见 [`DEPLOY.md`](DEPLOY.md)。**

这是纳入 `Academic-Research-Hub` 仓库扩展体系（`extensions/mcp/cfd-npy3d/`）的自包含 MCP server 扩展包。它提供两类工具：

- `npy3d_*`：面向 X/Y/Q `.npy` 存储的 CFD 平面场，做 3D 曲面图 / 时间 GIF 动画。
- `pvdata_*`：面向 ParaView 原生支持的文件格式（`.vtu/.vtp/.vti/.vts/.vtr/.vtk/.vtm/.ex2/.pvd/.xdmf/.stl/.ply/.obj/.csv...`），通过 **pvpython 任务桥** 读取数据，把网格点 + 标量/向量数组画成三维点云着色图或 GIF 动画。

可在 CodeBuddy / Claude Desktop 等客户端里作为第二个 MCP server 调用。

## 架构（v1.2 起，契约驱动）

参考 `academic-research-skills` 的「manifest + frontmatter + 一致性质量门」纪律组织，避免工具描述/参数/实现漂移：

```
tools/<name>.json + manifest.json   工具注册契约（数据驱动：名称/描述/参数）
registry.py                         契约加载与合法性校验
handlers.py                         工具的实现（显式签名）
server.py                           启动时按 registry 自动注册（不手写工具）
checks/check_registry_consistency.py  一致性质量门（可独立跑，也被 --selftest 集成）
skills/*/SKILL.md                   技能描述层（可选，二选一方式见下）
```

新增工具 = 加 `tools/<工具>.json` + manifest 登记 + handlers 实现 → 过质量门，无需改 server 主体。

## 能力

| 工具 | 适用数据 | 作用 |
|---|---|---|
| `npy3d_inspect` | `.npy` | 推断 `T/C/H×W`，输出文件大小、坐标范围、首帧各通道统计。 |
| `npy3d_render_surface` | `.npy` | 单帧 3D 曲面图：以 X/Y 为底面、Q 为 z 值和颜色。 |
| `npy3d_render_animation` | `.npy` | 单通道时间序列 3D 曲面 GIF 动画。 |
| `pvdata_inspect` | ParaView 格式 | 输出 reader 类型、包围盒、点/单元数、时间步、点/单元数组名称与范围。 |
| `pvdata_render_scatter3d` | ParaView 格式 | 指定数组某时间步的三维点云着色 PNG；向量自动取模，单元数组自动转点数组。 |
| `pvdata_render_animation` | ParaView 格式（时变） | 逐时间步点云着色 GIF 动画，颜色区间固定。 |
| `pvdata_import` | ParaView 格式 | x-y 平面 2D 场导入为 X/Y/Q `.npy`（支持 ParaView 全部 reader 格式，见 `skills/pvdata_import`），供 `npy3d_*` 渲染曲面/动画。 |

## 安装/注册

包内依赖与主 MCP 一致：`mcp`、`numpy`、`matplotlib`、`Pillow`。`pvdata_*` 通过本机已安装的 **ParaView `pvpython.exe`** 读取格式，无需额外 Python 包。

使用方式**二选一**：

- **方式 A（推荐）：MCP server 注册** —— 7 个工具以 `npy3d_*`/`pvdata_*` 出现在工具列表，见下节；
- **方式 B：skill 技能发现** —— 把 `skills/npy3d_visualization`、`skills/pvdata_visualization`、`skills/pvdata_import` 复制或软链到客户端技能目录（Claude Code：`.claude/skills/`），agent 按 SKILL.md 的描述自行决定调用流程（需客户端支持 agent skills）。

### 1. 在 CodeBuddy 中添加扩展 server（方式 A）

将 `mcp.example.json` 内容合并到你的 MCP 配置：

```json
{
  "mcpServers": {
    "cfd-npy-3d": {
      "command": "python",
      "args": ["g:/mcp-/cfd_npy3d_mcp/server.py"],
      "env": {
        "NPY3D_OUT_ROOT": "g:/mcp-/output",
        "PARAVIEW_PVPYTHON": "D:/Program Files/ParaView 6.0.1/bin/pvpython.exe"
      }
    }
  }
}
```

- `NPY3D_OUT_ROOT`：产物根目录，缺省为 `<server.py 上级目录>/output`。
- `PARAVIEW_PVPYTHON`：可选（兜底）。桥优先读包内 `config/paraview.json` 的 `pvpython.candidates`（推荐配置点，支持 `${VAR}` 展开与 glob），找不到再按 `PARAVIEW_PVPYTHON` → `PARAVIEW_BIN/pvpython.exe` → `PATH` → 常见安装路径查找。

### 2. 快速验证

```powershell
python g:\mcp-\cfd_npy3d_mcp\server.py --selftest
```

自测会：
0. 先跑一致性质量门（`manifest.json`/`tools/*.json` ↔ `handlers.py` 签名 ↔ `skills/` 文档）；
1. 生成 / 复用 `sample_data/` 的 `.npy` 演示数据；
2. 跑 `npy3d_inspect` / `npy3d_render_surface`（单通道 + 全通道） / `npy3d_render_animation`；
3. 若 `g:/mcp-/CFD_TEST` 存在真实 `.npy`，做兼容性检查并出一帧真实曲面；
4. 若 `pvpython` 可用且附近能找到 ParaView 自带 `disk_out_ref.ex2`，跑 `pvdata_inspect` / `pvdata_render_scatter3d` / `pvdata_render_animation`。

只想跑质量门：`python g:\mcp-\cfd_npy3d_mcp\server.py --check`（等价 `python checks/check_registry_consistency.py`）。

## 数据协议

### `.npy` 协议（`npy3d_*`）

- 同一目录下应有 X/Y/Q 三个 `.npy` 文件（文件名分词中含 `x` / `y` / `q` 即可匹配，如 `NACA_Cylinder_X.npy`）。
- `X/Y` 形状相同，支持 `(H,W)` 或 `(T,H,W)`。
- `Q` 支持 `(H,W)` / `(C,H,W)` / `(T,H,W)` / `(T,C,H,W)`。
- 读取使用 `mmap_mode='r'`，1 GB 级 `Q.npy` 不会整体载入内存。

### ParaView 文件协议（`pvdata_*`）

- 通过 pvpython 内置的 reader 映射读取文件，reader 与主 MCP 使用的 `pv_job.py` 同构，覆盖常见格式。
- 大数据自动均匀子采样到 `max_points`（默认 25 万点）。
- 多 block / composite 数据集会遍历每一块，只保留包含目标数组的块；跳过的块数会在结果中说明。
- 向量数组自动取模；CELL_DATA 数组会先经 `CellDatatoPointData` 转换后再使用。

## 示例调用

### `.npy`：检视示例数据

```
npy3d_inspect(data_dir="g:/mcp-/cfd_npy3d_mcp/sample_data")
```

### `.npy`：真实 CFD_TEST 出三维曲面

```
npy3d_render_surface(
  data_dir="g:/mcp-/CFD_TEST",
  frame=0,
  channels="0",
  case="naca_cylinder"
)
```

### ParaView 格式：检视 ex2

```
pvdata_inspect(file_path="D:/Program Files/ParaView 6.0.1/examples/disk_out_ref.ex2")
```

### ParaView 格式：三维点云着色图

```
pvdata_render_scatter3d(
  file_path="D:/Program Files/ParaView 6.0.1/examples/disk_out_ref.ex2",
  array_name="Temp",
  timestep_index=0,
  max_points=250000,
  case="mocvd_reactor"
)
```

### ParaView 格式：时间动画（时变文件）

```
pvdata_render_animation(
  file_path="...some.vtu",
  array_name="pressure",
  max_frames=24,
  max_points=120000,
  fps=6,
  case="case1"
)
```

## 产物归档

沿用主 MCP 的归档约定：

- 带 `case` 参数：`output/cases/<case>/render/<timestamp>.png/.gif`
- 不带 `case` 参数：`output/render/<timestamp>.png/.gif`
- 同秒多次写入自动加 `_1`、`_2` 守卫。

## 文件结构

```
cfd_npy3d_mcp/
├── server.py              # 入口：按 registry 自动注册工具（FastMCP stdio）
├── registry.py            # 契约加载/校验（manifest.json + tools/*.json）
├── handlers.py            # 7 个工具实现（显式签名，与契约一一对应）
├── core.py                # 执行层：X/Y/Q 协议解析 + 3D 曲面/点云/动画 绘制
├── pvbridge.py            # 定位 pvpython（config/paraview.json）并执行 JSON job 的桥
├── pvjob_pvdata.py        # 在 pvpython 下运行的 job 执行器（inspect/points/import2d）
├── manifest.json          # 工具/技能注册清单（契约索引）
├── tools/                 # 每个工具一份参数契约 JSON（7 个）
├── config/                # ParaView 工作配置（paraview.json / paraview_readers.json）
├── checks/                # 一致性质量门（check_registry_consistency.py）
├── skills/                # SKILL.md 技能描述层（二选一使用方式 B）
│   ├── npy3d_visualization/
│   ├── pvdata_visualization/
│   └── pvdata_import/
├── make_sample.py         # 生成 sample_data/ 演示数据
├── sample_data/           # 合成圆柱绕流 (48帧, 5通道, 81x201)
├── requirements.txt
├── mcp.example.json
├── DEPLOY.md              # 详细部署文档
└── README.md              # 本文件
```

## 已知限制

- `pvdata_*` 完全依赖本机 `pvpython`；找不到时会明确报错并提示设置 `PARAVIEW_PVPYTHON`。
- `.npy` 动画要求抽样帧不含 `NaN`；含 `NaN` 的通道会明确报错，建议换帧段/通道。
- `pvdata_render_scatter3d` 对 composite/multiblock 数据仅保留含目标数组的块，不显示被跳过的块。
- 图像内文字均用英文，避免 matplotlib 默认字体缺少中文字形。
- 未直接输出 `.vtu/.vts`；若以后需要把 `.npy` 转成 ParaView 格式，可再引入 `vtk` Python 包实现 `npy3d_export_*`。
