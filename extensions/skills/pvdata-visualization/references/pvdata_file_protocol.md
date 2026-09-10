# ParaView 文件读取协议（pvdata_* 依赖）

## 数据流

```
MCP 工具 (普通 Python)
   └─ pvbridge: 定位 pvpython.exe，执行 JSON job
        └─ pvjob_pvdata.py (pvpython 内运行):
               inspect job -> 元数据 JSON
               points job  -> 采样点 + 数组值 -> 紧凑 .npz (float32)
   普通 Python 读取 .npz -> matplotlib 绘图
```

临时 job/.npz 放在包内 `.run/`，每轮工具调用结束自动清理。

## 支持的格式

经 pvpython 内置 reader 映射读取（reader 映射与主 MCP 的 `pv_job.py` 同构），
覆盖常见扩展名：`.vtu/.vtp/.vti/.vts/.vtr/.vtk/.vtm/.ex2/.exo/.pvd/.xdmf/
.stl/.ply/.obj/.csv` 等。扩展名无法自动识别时可先跑
`mcp__cfd_npy3d__pvdata_inspect` 看报错。完整 reader 清单见
`extensions/mcp/cfd-npy3d/config/paraview_readers.json`。

## 时间步

- 检视返回 `TimestepValues` 列表；
- points 按 `timestep_index` 精确定位（`UpdatePipeline(time)` 后再取数据）；
- `timestep_index` 会被钳制到 `[0, N-1]`（<0 取 0，≥N 取最后一帧），**不报错**；
  返回的 `timestep_index/timestep_count` 反映实际命中帧。仅当数据集无时间步却给了非 0 索引时才报错。
- `pvdata_import` 的 `time_slice`（`0` / `0-4` / `all`）同样按上下界钳制。

## 数组处理

- 自动选择：不指定 `array_name` 时选首个标量点数组；
- 指定名未命中：**不报错**，静默回退到上面的“自动选择”规则（先首个标量，再首个数组）；
- CELL_DATA：`CellDatatoPointData` 转换（按单元中心转点值，单元型数据会被平滑）；
- 向量/张量：取模后作为标量着色；
- 非有限值（NaN/Inf）逐点剔除并统计；
- 单数组多分量时报告分量数。

## 大数据与采样

- 全量点先经 vtk 端收集，超过 `max_points` 时按均匀下标子采样；
- 结果同时返回 `npts_orig`（采样前点数）与 `npts_saved`，md 中说明；
- 防止 pvpython 侧内存爆掉：每帧只导出点坐标 + 一个数组（float32）。

## 产物约定

- PNG/GIF 归档到 `<产物根>/cases/<case>/render/` 或 `<产物根>/render/`；
- 图像文字固定英文；md 文本 UTF-8 中文。
