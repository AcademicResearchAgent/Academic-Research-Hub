---
name: pvdata-import
description: 把 ParaView 支持的任意格式数据文件（.vtu/.vtp/.vti/.vts/.vtr/.vtk/.vtm/.ex2/.pvd/.xdmf/.xmf/.nc/.foam/.stl/.ply/.obj/.csv 等全部 reader 格式，清单见 config/paraview_readers.json）导入本可视化管线：检视文件后，对 x-y 平面的 2D 数据场调用 pvdata_import 导出为 X/Y/Q .npy，交给 npy3d_inspect / npy3d_render_surface / npy3d_render_animation 渲染规则网格曲面与时间动画；三维体积场自动拒绝并引导改用 pvdata_render_scatter3d。数据经本机 pvpython（ParaView）任务桥读取。
data_access_level: raw
task_type: multi-step
permitted_tools:
  - pvdata_import
  - pvdata_inspect
  - pvdata_render_scatter3d
  - pvdata_render_animation
  - npy3d_inspect
  - npy3d_render_surface
  - npy3d_render_animation
---

# pvdata 数据导入（ParaView 全格式 → X/Y/Q .npy）

## 用途

把 ParaView 能读的文件（本机 ParaView 的 reader 决定"能读"，
`config/paraview_readers.json` 是本机枚举的权威格式清单）导入为本工具链统一的
**X/Y/Q .npy**，从而用 `npy3d_*` 画结构化三维曲面与时间序列 GIF：

- **导入**：`pvdata_import` 把 x-y 平面、z 无厚度的 2D 场导出为 `X.npy / Y.npy / Q.npy`
  （规则网格协议：单帧 `(H,W)`，多帧 `(T,H,W)`）；
- **检视**：`pvdata_inspect` 先看 reader/包围盒/时间步/数组清单，判断是否 2D 平面场；
- **渲染**：导入后交给 `npy3d_inspect / npy3d_render_surface / npy3d_render_animation`。

## 何时使用 / 何时不用

使用：源数据是 ParaView 可读文件（CFD/有限元/成像等结果），且关心的是
**规则网格曲面形态**（NACA 翼型贴体网格、圆柱绕流平面场等 x-y 平面量场）；
想用 X/Y/Q 协议继续做帧/通道渲染或动画。

不用：
- 三维体积场（z 有厚度）→ `pvdata_import` 会拒绝，改用 `pvdata_render_scatter3d / pvdata_render_animation`；
- 只想快速看散点形态 → 直接用 `pvdata_visualization` 技能；
- 源数据已是 `.npy` → 直接 `npy3d_*`，无需导入；
- 本机无 ParaView → 工具明确报错并提示设置 `PARAVIEW_PVPYTHON`。

## 工具

| 工具 | 作用 |
|---|---|
| `pvdata_import` | 核心：ParaView 任意格式 2D 平面场 → X/Y/Q .npy（结构化直导 / 非结构最近点重采样） |
| `pvdata_inspect` | 导入前检视：reader/包围盒/时间步/数组清单（判断是否 2D、数组名） |
| `pvdata_render_scatter3d` | 三维体积场/点云的兜底可视化 |
| `pvdata_render_animation` | 三维体积场/点云的逐时间步动画 |
| `npy3d_inspect` | 导入后核对 X/Y/Q 数据集（T/C/H/W 推断） |
| `npy3d_render_surface` | 导入后的规则网格三维曲面 PNG |
| `npy3d_render_animation` | 导入后的时间序列曲面 GIF |

## 标准流程

1. **检视源文件**：`pvdata_inspect(file_path=<文件>)` —— 看 bounds（z span ≈ 0 才是 2D
   平面场）、timesteps、数组名；
2. **导入**：`pvdata_import(file_path=..., array_name=<数组>, time_slice="0" | "0-4" | "all",
   sample_w=<宽，0=自动>, sample_h=<高，0=自动>, case=<归档名>)`；
   - 结构化网格（`vtkImageData`/`vtkRectilinearGrid`/`vtkStructuredGrid`）保持原网格直导；
   - 非结构化/多块数据自动 `MergeBlocks` 并最近点重采样为规则 W×H（默认长轴 320），
     数据域外为 NaN；
   - 返回 `data_dir`（`X.npy/Y.npy/Q.npy` 所在目录）。
3. **渲染**：`npy3d_render_surface(data_dir=<上一步 data_dir>, frame=<0..T-1>, channels="0", case=...)`
   或 `npy3d_render_animation(data_dir=..., channel=0, max_frames=48, fps=6)`。

## 自动处理规则

- CELL 数组自动 `CellDatatoPointData`；多分量数组自动取模长；
- composite/多块文件先合并再导入；
- `time_slice` 多帧时 Q 存 `(T,H,W)`，X/Y 沿 T 广播（协议要求 X/Y 与 Q 同秩）；
- 数据域外的重采样点/无数组块自动置 NaN，返回 NaN 占比；
- 3D 体积场（z span > 容差）直接拒绝并提示改用 pvdata 点云渲染。

## 输出

Markdown 报告：reader、数组（association/components）、采样方式、
W×H、帧数（时间索引）、NaN 占比、bounds、产物 `data_dir` 路径；
后续每个渲染工具的 `data_dir` 都可直接填它。

## 示例

```
pvdata_import(file_path="E:/sim/blade_surface.vtu", array_name="pressure",
              time_slice="0-4", sample_w=640, case="blade")
→ npy3d_render_surface(data_dir=..., frame=4, channels="0", case="blade")
```

## 限制

- 只支持 x-y 平面 2D 场（z 无厚度）；三维请走 `pvdata_render_scatter3d`；
- 表格类数据（如纯 CSV 点表）不是网格场，无法结构化导入，用点云渲染；
- 本机 ParaView 未安装 / `PARAVIEW_PVPYTHON` 未配置时不可用（见
  `docs/development/PARAVIEW-INTEGRATION.md` 与包内 `config/paraview.json`）。

## 参考

- `references/pvdata_supported_formats.md` —— ParaView 全格式支持说明与 2D 判定
- `config/paraview_readers.json` —— 本机 pvpython 枚举的 reader/扩展名权威清单
