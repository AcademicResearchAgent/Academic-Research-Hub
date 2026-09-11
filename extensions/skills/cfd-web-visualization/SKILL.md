---
name: cfd-web-visualization
description: 选中本技能后，为 CFD 数据打开「Web 端物理图像渲染引擎」入口：默认以弹出独立新界面方式打开渲染引擎（与工作站统一的深色科研风 UI），支持导入格式的数据文件（X/Y/Q .npy 平面场目录，或 ParaView 常见格式 .vtk/.vtu/.vti/.vts/.vtr/.vtp/.ex2/.vtm/.pvd/.xdmf/.xmf/.stl/.ply/.obj/.csv），在浏览器里实时交互观测三维物理场（旋转/缩放/平移、切时间帧、换物理量通道、换色图、调颜色范围），并由用户按需选择是否把当前视图导出为论文插图（PNG + LaTeX figure 片段）。适用于想「边算边看」「交互式调参观察」或「直接取图入论文」的场景。
---

# CFD Web 可视化工作台（数据导入 + 实时渲染 + 论文插图）

## 用途

把「选数据 → 实时看 → 按需出图」收敛到一个浏览器工作台：

- **弹出式入口**：选中技能后返回「弹出式启动页」地址，使用时会弹出**独立渲染新界面**
  （与工作站同一套深色科研风 UI，宽高/缩放/视角独立保持，便于与工作站界面并行观测）；
- **数据导入入口**：把支持格式的数据文件导入统一产物根，供渲染引擎读取；
- **实时渲染引擎**：浏览器内 WebGL 三维渲染，交互式旋转/缩放/平移，切时间帧、
  换物理量通道、换色图、调颜色范围；
- **导出到论文（可选）**：一键把当前视图截帧为论文级 PNG，并生成可粘贴的
  LaTeX `figure` 片段——**是否导出完全由用户选择**，不启用则不产生任何论文产物。

## 何时使用 / 何时不用

使用：用户想实时观察三维物理场、需要交互式调参看图、或希望直接把图放进论文。

不用：只要一张固定角度的静态图或 GIF 时，直接用 `npy3d-visualization` /
`pvdata-visualization` 技能更省事；数据不在本管线支持的格式内时先看
`pvdata-import` 技能的格式清单。

## 工具

本技能的工具由 `cfd_npy3d` MCP server 提供，Hermes 中的完整名称为 `mcp__cfd_npy3d__<工具名>`。

| 工具 | 作用 |
|---|---|
| `mcp__cfd_npy3d__npy3d_web_viewer` | 工作台入口：默认返回**弹出式启动页**地址（弹出独立渲染新界面）+ 支持格式清单 + 已发现数据集；传 `file_path` 时先导入该文件 |
| `mcp__cfd_npy3d__npy3d_inspect` | 导入的是 .npy 数据集时，先核对 T/C/H×W 与各通道范围 |
| `mcp__cfd_npy3d__pvdata_inspect` | 导入的是 ParaView 文件时，先核对 reader/包围盒/时间步/数组清单 |
| `mcp__cfd_npy3d__pvdata_import` | x-y 平面 2D 场 → X/Y/Q .npy（渲染引擎也会自动尝试这一步） |

## 标准流程

1. **给入口**：`mcp__cfd_npy3d__npy3d_web_viewer()` 拿到弹出式启动页地址；打开后即
   弹出独立渲染新界面，并列出当前支持格式、数据集清单；
2. **导入数据**（二选一）：
   - 用户在渲染引擎页面左侧「数据导入」上传文件或填服务器路径；或
   - 让工具代劳：`mcp__cfd_npy3d__npy3d_web_viewer(file_path="<支持格式文件绝对路径>")`；
3. **实时观测**：在页面里旋转/缩放/平移，拖动时间帧，切换物理量通道与色图；
4. **（可选）导出到论文**：用户勾选时点「导出到论文」→ 填 caption/label →
   得到 PNG + LaTeX 片段；或调用
   `mcp__cfd_npy3d__npy3d_web_viewer(..., embed_in_paper=True)` 获取引导。

## 支持的导入格式

- **X/Y/Q .npy 平面场**：同一目录含 `X.npy` / `Y.npy` / `Q.npy`，
  Q 布局 `(H,W)/(C,H,W)/(T,H,W)/(T,C,H,W)`；
- **ParaView 常见格式**：`.vtk .vtu .vti .vts .vtr .vtp .ex2 .vtm .pvd .xdmf .xmf .stl .ply .obj .csv`
  （x-y 平面 2D 场可一键转为 X/Y/Q .npy 规则曲面，其余按三维点云渲染）。

清单单一事实源：`extensions/mcp/cfd-npy3d/webviewer/formats.json`（后端与前端共用）。

## 参数约定

- `data_dir`：要扫描的数据目录；缺省依次取 `CFD_DATA_DIR`、包内上级 `exp_data`；
- `file_path`：可选，先导入该文件再返回入口；
- `dataset` / `frame` / `channel`：用于生成带预选参数的入口 URL；
- `embed_in_paper`：是否附加论文导出引导（默认 `false`，完全由用户选择）；
- `open_in`：入口打开方式，`popup`（默认）弹出独立渲染新界面，`tab` 在浏览器标签页打开。

## 输出与产物

- 工具返回 Markdown（含入口 URL、格式表、数据集清单）。
- 导入产物：`<产物根>/import/<case>/...`；2D 场转换结果在
  `<产物根>/import/<case>/data/X.npy|Y.npy|Q.npy`。
- 论文插图：`<产物根>/figures/*.png`，并给出对应 LaTeX `\includegraphics` 片段。
- 产物根可用环境变量 `NPY3D_OUT_ROOT` 覆盖。

## 示例

```
mcp__cfd_npy3d__npy3d_web_viewer()
mcp__cfd_npy3d__npy3d_web_viewer(file_path="E:/sim/cavity.vtu", embed_in_paper=True)
mcp__cfd_npy3d__npy3d_web_viewer(data_dir="E:/CFD_TEST", dataset="NACA_Cylinder", frame=12, channel=0)
mcp__cfd_npy3d__npy3d_web_viewer(dataset="NACA", open_in="tab")
```

## 限制与注意

- 需先启动 HTTP 桥：`python http_bridge.py --host 127.0.0.1 --port 8765`。
- 入口地址：弹出式启动页 `http://127.0.0.1:8765/viewer/launch`；
  渲染引擎本体 `http://127.0.0.1:8765/viewer`；跨机访问用 `CFD_BRIDGE_PUBLIC_BASE`。
- 渲染服务是**技能后端**，不是可自由浏览的网站：查看器页面与 `/api/*` 需带技能共享令牌
  （`?t=<token>`）。令牌由 `webviz.bridge_token()` 生成并随本技能返回的入口 URL 自动携带，
  无需手工拼接；直接在浏览器打开不带令牌的地址会看到「技能专用」提示页。
- 弹出独立新界面依赖浏览器弹窗权限：被拦截时在启动页点击「打开渲染新界面」即可；
  渲染窗口顶栏「弹出新窗口」可再开一个并行对照窗口。
- ParaView 文件转 2D 场需要本机 `pvpython`；缺失时自动退化为三维点云渲染。
- 浏览器渲染用降采样后的几何（默认上限约 6 万点），大网格会做 stride 抽样。
- 论文导出为纯静态 PNG（前端截帧）；需要透明背景/矢量图时改用
  `npy3d_render_surface` 出图再插入论文。

## 失败与边界

- 未启动 HTTP 桥：入口 URL 打不开，先按上文启动；工具本身仍会返回格式与数据集清单。
- 浏览器拦截弹窗：启动页会提示并给出「打开渲染新界面」按钮，点击即可；或改用 `open_in="tab"`。
- 导入不支持扩展名：工具报告支持的格式清单，不猜测数据语义。
- 目录里只导入到部分 `.npy`：报告缺失的字段，提示补齐 X/Y/Q 后再渲染。
- 大网格渲染卡顿：调低页面里的采样上限或换更粗的网格。

## 参考

- HTTP 接口与载荷协议：`references/web_rendering.md`
- 数据协议细节：`../npy3d-visualization/references/npy_data_protocol.md`
- ParaView 全格式：`../pvdata-import/references/pvdata_supported_formats.md`
