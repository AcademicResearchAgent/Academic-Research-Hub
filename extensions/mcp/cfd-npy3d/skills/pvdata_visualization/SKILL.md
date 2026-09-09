---
name: pvdata-visualization
description: 把 ParaView 原生支持的常见文件格式（.vtu/.vtp/.vti/.vts/.vtr/.vtk/.vtm/.ex2/.pvd/.xdmf/.stl/.ply/.obj/.csv 等）做三维可视化：检视数据集（reader/包围盒/点单元数/时间步/数组清单）、指定数组某时间步的三维点云着色图、时变文件的逐时间步点云 GIF 动画。数据经本机 pvpython（ParaView）任务桥读取，绘图在 matplotlib 完成。
data_access_level: raw
task_type: multi-step
permitted_tools:
  - pvdata_inspect
  - pvdata_render_scatter3d
  - pvdata_render_animation
  - pvdata_import
---

# pvdata 三维可视化（ParaView 常见格式）

## 用途

输入是一个 ParaView 可读文件（网格类或点云类），把它变成三维图：

- 检视：reader 类型、包围盒、点/单元数、时间步、POINT/CELL 数组清单；
- 单帧点云着色：以网格点坐标为散点位置，以某数组值着色；
- 时变动画：多时间步逐帧着色 GIF，颜色区间全局固定（不闪动）。

## 何时使用 / 何时不用

使用：文件是 ParaView 原生格式；要看结构网格/非结构网格/粒子数据的
三维形态，或时变数据的演化。

不用：数据是 numpy `.npy`（走 `npy3d_*` / npy3d-visualization 技能）；
本机没有 ParaView（工具会明确报错并提示设置 `PARAVIEW_PVPYTHON`）。

## 工具

| 工具 | 作用 |
|---|---|
| `pvdata_inspect` | 检视文件：reader/包围盒/点数/时间步/数组清单（先检视再画图，避免瞎猜数组名与时间步） |
| `pvdata_render_scatter3d` | 指定数组某时间步三维点云着色 PNG |
| `pvdata_render_animation` | 时变文件逐时间步点云 GIF（时间步很多的文件较慢，先 inspect 看步数再定 max_frames） |
| `pvdata_import` | 仅用于 x-y 平面 2D 场：导入为 X/Y/Q .npy 交给 npy3d_* 渲染曲面（详见 `pvdata-import` 技能） |

## 标准流程

1. **检视**：`pvdata_inspect(file_path=<文件>)` 拿到数组名、时间步、点数量级；
2. **单帧**：`pvdata_render_scatter3d(file_path=..., array_name=<数组>, timestep_index=<步>, case=<归档名>)`；
3. **动画**（有多个时间步时）：`pvdata_render_animation(file_path=..., array_name=<数组>, max_frames=<帧数>, case=<归档名>)`。

## 自动处理规则

- 不指定 `array_name`：自动选首个标量数组；
- CELL_DATA 数组：自动 `CellDatatoPointData` 转点数组；
- 向量数组：自动取模（模值着色）；
- composite/multiblock：遍历所有叶子块，只保留含目标数组的块（跳过数会在结果中说明）；
- 大数据：均匀子采样到 `max_points`（scatter3d 默认 25 万，animation 默认 12 万）。

## 输出与产物

- 工具返回 Markdown（含产物绝对路径与读取统计）。
- 带 `case`：`<产物根>/cases/<case>/render/`；不带 `case`：`<产物根>/render/`。
- 图内文字为英文；动画 GIF 用 pillow 编码。

## 示例

```
pvdata_inspect(file_path="D:/Program Files/ParaView 6.0.1/examples/disk_out_ref.ex2")
pvdata_render_scatter3d(file_path="D:/Program Files/ParaView 6.0.1/examples/disk_out_ref.ex2", array_name="Temp", timestep_index=0, case="mocvd_reactor")
pvdata_render_animation(file_path="E:/sim/case.pvd", array_name="pressure", max_frames=24, fps=6, case="sim1")
```

## 限制与注意

- 依赖 pvpython：查找顺序 `PARAVIEW_PVPYTHON` → `PARAVIEW_BIN/pvpython.exe` → PATH → 常见安装路径；
- 首次调用会启动一次 pvpython，耗时数秒属正常；
- 静态单时间步文件也能做“动画”，但帧间相同（先 inspect 确认时间步数）；
- 每个时间步独立走一次 pvpython 导出，时间步多时耗时可观，建议限制 max_frames。

## 参考

- 数据读取与导出协议：`references/pvdata_file_protocol.md`
