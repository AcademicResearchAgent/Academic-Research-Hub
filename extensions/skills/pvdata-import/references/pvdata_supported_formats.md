# ParaView 支持的格式清单与 2D 平面场判定

## 权威清单：`extensions/mcp/cfd-npy3d/config/paraview_readers.json`

本包运行于本机 ParaView（`pvpython`）。“哪些格式能导入”由 ParaView 的
reader 工厂决定，且随安装版本变化。仓库内置一份**本机枚举清单**：

```
extensions/mcp/cfd-npy3d/config/paraview_readers.json
```

它由 `pvpython` 遍历 `paraview.simple` 中全部 `*Reader` 生成，记录每个 reader 的
**扩展名**与**文件描述**（`ReaderFactory` hints）。在任意支持 reader 的文件上，
`mcp__cfd_npy3d__pvdata_import` 首先按扩展名选择显式 reader，未命中扩展名时用
`pvs.OpenDataFile` 让 ParaView 自动探测兜底，因此 **reader 清单中的全部格式
均可导入**。

如需在自己机器上重新生成该清单（或升级 ParaView 后刷新），在包目录
`extensions/mcp/cfd-npy3d/` 下用 pvpython 运行：

```bash
pvpython checks/export_paraview_readers.py --out config/paraview_readers.json
```

## 常见格式分组（示例，非穷尽）

| 分组 | 扩展名示例 | 典型 reader |
|---|---|---|
| XML/VTK 系列 | `.vti .vtu .vtp .vts .vtr .vtm .pvti .pvtu .pvtp` | XML*Reader / XMLMultiBlockDataReader |
| 经典 VTK | `.vtk` | LegacyVTKReader |
| 几何/网格 | `.stl .ply .obj .g .3ds .dem .cgns` | STL/PLY/OBJ/BYU/3DS/DEM/CGNS |
| 有限元/CFD 求解器 | `.ex2 .exo .e .foam .cas .dat .res .msh` | Exodus/OpenFOAM/FLUENT/MFIX/Gambit |
| 时变/装配 | `.pvd .vtm .vtmb .xdmf .xmf` | PVD/XDMF/MultiBlock |
| 科学数据 | `.nc .h5 .xmf .silo .p3d .plot3d` | NetCDF/HDF/Silo/PLOT3D |
| 表/点云 | `.csv` | CSVReader（点表，非网格场） |

> 完整、权威的扩展名↔reader 映射以
> `extensions/mcp/cfd-npy3d/config/paraview_readers.json` 为准；上表只用于快速概览。

## 是否“2D 平面场”的判定

`mcp__cfd_npy3d__pvdata_import` 逐帧读取数据包围盒，若

```
z_span <= max(1e-6, 1e-3 * max(x_span, y_span))
```

即 z 方向无厚度，才可导入为 X/Y/Q（规则网格曲面）；否则报错并提示三维
数据改用 `mcp__cfd_npy3d__pvdata_render_scatter3d / pvdata_render_animation`。

典型 2D 平面场来源：

- `vtkImageData`：z 方向 1 层（dims z = 1）；
- `vtkRectilinearGrid` / `vtkStructuredGrid`：z 单层贴体网格（NACA 翼型剖面等）；
- 非结构化 2D 网格 / 多块合并后的平面数据（重采样为规则网格）。

## 导入路径总结

```text
ParaView 可读文件
   ├─ 检视 pvdata_inspect（bounds/timesteps/数组）
   ├─ 2D 平面场 ──> pvdata_import ──> X/Y/Q .npy ──> npy3d_render_surface / _animation
   └─ 3D 体积场 / 点云 / 点表 ──> pvdata_render_scatter3d / pvdata_render_animation
```
