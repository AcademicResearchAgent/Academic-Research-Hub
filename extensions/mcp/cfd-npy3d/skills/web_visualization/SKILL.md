---
name: cfd-web-visualization
description: 选中本技能后为 CFD 数据提供「Web 端物理图像渲染引擎」入口：默认以弹出独立新界面方式打开渲染引擎（与工作站统一的深色科研风 UI），导入支持格式的数据文件（X/Y/Q .npy 平面场目录，或 ParaView 常见格式 .vtk/.vtu/.vti/.vts/.vtr/.vtp/.ex2/.vtm/.pvd/.xdmf/.stl/.ply/.obj/.csv），在浏览器里实时交互观测三维物理场（旋转/缩放/切时间帧/换物理量通道/换色图），并由用户按需选择是否把当前视图导出为论文插图（PNG + LaTeX figure 片段）。适用于用户想「边算边看」「实时调参观察」或「直接取图入论文」的场景。
data_access_level: raw
task_type: multi-step
permitted_tools:
  - npy3d_web_viewer
  - npy3d_inspect
  - pvdata_inspect
---

# CFD Web 可视化工作台（数据导入 + 实时渲染 + 论文插图）

## 用途

把「选数据 → 实时看 → 按需出图」这条链路收拢到一个浏览器工作台里：

- **弹出式入口**：选中技能后返回「弹出式启动页」地址，使用该技能时会弹出**独立渲染新界面**（与工作站同一套深色科研风 UI，宽高/缩放/视角独立保持，便于与工作站界面并行观测）；
- **数据导入入口**：把支持格式的数据文件导入统一产物根，供渲染引擎读取；
- **实时渲染引擎**：浏览器内 WebGL 三维渲染，交互式旋转/缩放/平移、切时间帧、换通道、换色图、调颜色范围；
- **导出到论文（可选）**：把当前视图一键截帧为论文级 PNG，并生成可粘贴的 LaTeX `figure` 片段——**是否导出完全由用户选择**，不启用则不产生任何论文产物。

## 何时使用 / 何时不用

使用：用户想实时观察三维物理场、需要交互式调参看图、或希望直接把图放进论文；
不适合：只要一张固定角度的静态图 / GIF 时，直接用 `npy3d_render_surface`、
`npy3d_render_animation`、`pvdata_render_scatter3d` 更省事。

## 工具

| 工具 | 作用 |
|---|---|
| `npy3d_web_viewer` | 打开工作台入口：默认返回**弹出式启动页**地址（弹出独立渲染新界面）+ 支持格式清单 + 已发现数据集；传 `file_path` 时先导入该文件 |
| `npy3d_inspect` | 导入的是 .npy 数据集时，先用它确认 T/C/H×W 与各通道范围 |
| `pvdata_inspect` | 导入的是 ParaView 文件时，先用它确认 reader/包围盒/数组清单 |

## 标准流程

1. **给入口**：`npy3d_web_viewer()` 拿到弹出式启动页地址；打开后即弹出独立渲染新界面，并列出当前支持格式/数据集；
2. **导入数据**（二选一）：
   - 在渲染引擎页面左侧「数据导入」上传文件 / 填服务器路径；或
   - 让工具代劳：`npy3d_web_viewer(file_path="<支持格式文件绝对路径>")`；
3. **实时观测**：在页面里旋转/缩放、拖动时间帧、切换物理量通道与色图；
4. **（可选）导出到论文**：用户勾选时点「导出到论文」→ 填 caption/label → 得到 PNG + LaTeX 片段；
   或调用 `npy3d_web_viewer(..., embed_in_paper=True)` 获取引导。

## 支持的导入格式

- **X/Y/Q .npy 平面场**：同一目录含 `X.npy` / `Y.npy` / `Q.npy`，
  Q 布局 `(H,W)/(C,H,W)/(T,H,W)/(T,C,H,W)`；
- **ParaView 常见格式**：`.vtk .vtu .vti .vts .vtr .vtp .ex2 .vtm .pvd .xdmf .xmf .stl .ply .obj .csv`
  （x-y 平面 2D 场可一键转成 X/Y/Q .npy 规则曲面，其余按三维点云渲染）。

清单单一事实源：`webviewer/formats.json`（渲染引擎与后端共用）。

## 参数约定

- `data_dir`：要扫描的数据目录；缺省依次取 `CFD_DATA_DIR`、包内上级 `exp_data`；
- `file_path`：可选，导入该文件后再返回入口；
- `dataset`/`frame`/`channel`：用于生成带预选参数的入口 URL；
- `embed_in_paper`：是否附加论文导出引导（默认 `false`，完全由用户选择）；
- `open_in`：入口打开方式，`popup`（默认）弹出独立渲染新界面，`tab` 在浏览器标签页打开。

## 输出与产物

- 工具返回 Markdown（含入口 URL、格式表、数据集清单）。
- 导入产物：`<产物根>/import/<case>/...`；2D 场转换结果在 `<产物根>/import/<case>/data/X.npy|Y.npy|Q.npy`。
- 论文插图：`<产物根>/figures/*.png`，并给出对应 LaTeX `\includegraphics` 片段。
- 产物根可用环境变量 `NPY3D_OUT_ROOT` 覆盖。

## 示例

```
npy3d_web_viewer()
npy3d_web_viewer(file_path="E:/sim/cavity.vtu", embed_in_paper=True)
npy3d_web_viewer(data_dir="E:/CFD_TEST", dataset="NACA_Cylinder", frame=12, channel=0)
npy3d_web_viewer(dataset="NACA", open_in="tab")
```

## 限制与注意

- 需先启动 HTTP 桥：`python http_bridge.py --host 127.0.0.1 --port 8765`。
- 入口地址：弹出式启动页 `http://127.0.0.1:8765/viewer/launch`；查看器本体 `http://127.0.0.1:8765/viewer`。
- 弹出独立新界面依赖浏览器弹窗权限：被拦截时在启动页点击「打开渲染新界面」即可；窗口内顶栏「弹出新窗口」可再开一个并行对照窗口。
- 跨机访问时用 `CFD_BRIDGE_PUBLIC_BASE` 指定对外基址。
- ParaView 文件转 2D 场需要本机 `pvpython`；缺失时自动退化为三维点云渲染。
- 浏览器渲染用降采样后的几何（默认上限约 6 万点），大网格会做 stride 抽样。

## 参考

- 格式单一事实源：`webviewer/formats.json`（后端 `webviz.load_formats()` 与前端共用）
- 数据协议：`../npy3d_visualization/references/npy_data_protocol.md`
- ParaView 全格式：`../pvdata_import/references/pvdata_supported_formats.md`
