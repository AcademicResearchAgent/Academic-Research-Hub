# data_format_read —— 常见数据格式读取能力自检

验证 `cfd-npy3d` 扩展（`pvdata_inspect` / `pvdata_render_*` / `pvdata_import2d`
共同的底层读取路径 `pvjob_pvdata.run_inspect()`）当前能读取哪些常见数据格式。

## 运行

```powershell
cd G:\new\Academic-Research-Hub\extensions\mcp\cfd-npy3d
python -m checks.data_format_read.run_format_read_check
```

可选参数为样例输出目录（默认 `.run/data_format_read`，已被 `.gitignore` 忽略）：

```powershell
python -m checks.data_format_read.run_format_read_check .run/dfr_out
```

## 流程

1. 定位 pvpython（读 `config/paraview.json` 的候选路径，找不到则检查失败）；
2. 用 pvpython 执行 `make_samples_pv.py <out_dir>`：
   - **现场生成 tiny 样例**：`.vti .vtu .vtp .vts .vtr .vtk .vtm .stl .ply .obj .csv .pvd`
     （`.ex2/.e` 若无 ParaView 自带样例则跳过，`.xdmf` 取决于本机是否有
     `vtkXdmfWriter`）；
   - **同一进程内**对每个样例调用扩展真实读取实现
     `pvjob_pvdata.run_inspect()`（与 `pvdata_inspect` 完全一致），
     记录 reader、points/cells、数组名、时间步；
   - 结果与清单写回 `<out_dir>/samples.json`；
3. 驱动按每格式输出支持矩阵并汇总 PASS/FAIL/SKIP。

## 判定口径

- `PASS`：reader 能打开且与 `pvjob_pvdata.READERS` 映射一致，并读出
  points/cells/数组（表格 `vtkTable`、多块 composite 顶层无 points 属正常）；
- `WARN`：reader 能打开，但顶层 points/cells/arrays 全为 0；
- `FAIL`：读取报错，或实际 reader 与 `READERS` 表期望不符
  （说明映射的 reader 名在本机 `paraview.simple` 中不存在）；
- `SKIP`：本机无法生成该格式样例（如缺 ParaView 示例 ex2、无 XDMF writer）。

`run()` 返回 `(ok, lines)`，可被其它自检入口复用；`main()` 直接打印表格，
非零退出码表示存在 FAIL。

## 覆盖格式与对应 reader（pvjob_pvdata.READERS）

| 扩展名 | READERS 映射 | 说明 |
|---|---|---|
| .vti | XMLImageDataReader | 结构均匀网格 |
| .vtu | XMLUnstructuredGridReader | 非结构网格 |
| .vtp | XMLPolyDataReader | 多边形数据 |
| .vts | XMLStructuredGridReader | 结构网格 |
| .vtr | XMLRectilinearGridReader | 规则网格 |
| .vtk | LegacyVTKReader | 旧版 ASCII/二进制 |
| .vtm/.vtmb | XMLMultiBlockDataReader | 多块集合 |
| .stl | STLReader | 三角网格 |
| .ply | PLYReader | 点云/网格 |
| .obj | WavefrontOBJReader | Wavefront OBJ |
| .csv | CSVReader | 表格 |
| .ex2/.exo/.e | ExodusIIReader | Exodus 有限元结果 |
| .pvd | PVDReader | VTK 时间集合 |
| .xdmf/.xmf | XDMFReader | XDMF 数据 |

> 注意：不同 ParaView 版本中 `.obj` 的代理名可能不同，本表以 `config/paraview_readers.json`
> 在本机枚举到的 `WavefrontOBJReader` 为准（历史上曾映射为不存在的 `OBJReader` 导致
> `.obj` FAIL）。其余未在表中列出的扩展名会走 `pvs.OpenDataFile()` 自动探测。
