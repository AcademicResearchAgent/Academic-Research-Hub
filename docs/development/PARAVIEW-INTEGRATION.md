# ParaView 集成配置（cfd_npy3d 扩展 / pvdata_*）

核对日期：2026-09-08。本文说明 ParaView 工作所需的全部配置如何在 Academic-Research-Hub（下称 ARH）内集中管理：
pvpython 定位、reader 支持清单、`pvdata_import` 导入链路，以及本地验证方式。

## 1. 涉及位置总览

```text
extensions/mcp/cfd-npy3d/
├── server.py                    MCP stdio 入口（注册 7 个工具）
├── pvbridge.py                  读 config/paraview.json 定位 pvpython + 执行 job（普通 Python 侧）
├── pvjob_pvdata.py              pvpython 侧 job 执行器（inspect / points / import2d）
├── config/
│   ├── paraview.json            ★ pvpython 定位与 job 超时（本机可改）
│   └── paraview_readers.json    ★ ParaView reader 类名 + 常见扩展名映射（自动生成）
├── checks/
│   ├── check_registry_consistency.py   契约一致性质量门
│   └── export_paraview_readers.py      （重新）枚举 reader 清单
├── skills/pvdata_visualization/ 点云着色 / 动画技能
├── skills/pvdata_import/        导入 ParaView 任意类型 2D 数据为 X/Y/Q 技能
└── make_sample.py                生成演示数据（含 plane2d.vtk 供 import2d 自测）
```

扩展发布配置（与所有扩展一致）：

```text
configs/workstation/extensions.json       本项目发布配置（工具白名单）
scripts/package_extensions.py             打包源码与部署器
deploy/hermes/deploy-extensions.py        依赖安装 / 配置合并
```

## 2. pvpython 定位（config/paraview.json）

`pvbridge.py` 启动时读取 `config/paraview.json`，按 `pvpython.candidates` 顺序取第一个存在的可执行文件：

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

- 支持 `${VAR}` 环境变量展开与 `*`/`?` glob。
- config 找不到时，回退顺序为 `PARAVIEW_PVPYTHON` → `PARAVIEW_BIN/pvpython.exe` → `PATH` → 内置常见路径。
- 本机路径变更时**只改这个 json**，不碰代码与 C 盘 `.codebuddy`。

验证（打印实际使用的 pvpython 路径）：

```powershell
python -c "import sys; sys.path.insert(0,'extensions/mcp/cfd-npy3d'); import pvbridge; print(pvbridge.find_pvpython())"
```

## 3. reader 支持清单（config/paraview_readers.json）

- 由 `checks/export_paraview_readers.py` 枚举生成：读取 ParaView 的 reader 类名（共 183 个），合并常见扩展名映射。
- 工具据此做「扩展名 → reader 代理类」匹配，找不到时回退 `OpenDataFile`。
- 重新生成：

```powershell
python extensions/mcp/cfd-npy3d/checks/export_paraview_readers.py
```

> 个别 reader 依赖第三方 codec，打开时可能失败（例如 ADIOS2/CONVERGE 等）；清单只保证「PV 认识该格式」，不保证数据可解码。

## 4. pvdata_import 导入链路（2D 平面场 → X/Y/Q .npy）

`pvdata_import` 把 ParaView 支持的文件（`.vtu/.vtp/.vti/.vts/.vtr/.vtk/.vtm/.ex2/.pvd/.xdmf/.stl/.ply/.obj/.csv…`）中任意标量/向量数组
导入为 `X/Y/Q` `.npy`（协议与 `npy3d_*` 完全一致）：

| 数据集类型 | 处理方式 |
| --- | --- |
| 结构化平面场（vtkImageData / RectilinearGrid / StructuredGrid，z 无厚度） | 原生结构化网格直导，保留 (H,W) 规则网格 |
| 非结构化 / 曲面（x-y 平面，z 无厚度） | 最近邻规则网格重采样（可传 `sample_w/sample_h`） |
| CELL 关联数组 | 自动转 POINT 再导入 |
| 时变 / composite（ex2 多 block、pvd 序列） | 逐时间步合并后导入，`time_slice` 控制取帧 |
| 3D 体积场（z 有厚度） | 明确拒绝并提示改走 `pvdata_visualization` 点云路径 |

判定规则：`z_span <= max(1e-6, 1e-3 * max(x_span, y_span))` 视为平面。

产物目录约定（X.npy / Y.npy / Q.npy），可被 `npy3d_render_surface` / `npy3d_render_animation` 直接消费。

## 5. 本机验证（selftest 已含 import2d E2E）

```powershell
# 质量门 + 全自测（含 pvdata import2d E2E，要求 pvpython 可用）
python extensions/mcp/cfd-npy3d/server.py --selftest

# 仅契约一致性质量门
python extensions/mcp/cfd-npy3d/server.py --check
```

自测第 5b 步流程：

1. `make_sample.py` 生成 `sample_data/plane2d.vtk`（ASCII legacy 2D 平面场）；
2. 调 `pvdata_import` → 断言产出 `X.npy / Y.npy / Q.npy`；
3. 调 `npy3d_render_surface` 消费产物 → 断言渲染出 PNG。

ParaView 官方自带示例 `disk_out_ref.ex2` 为 3D 体积，仅用于 `pvdata_inspect / pvdata_render_scatter3d / pvdata_render_animation` 的验收。

## 6. 常见问题

| 现象 | 处理 |
| --- | --- |
| `pvpython.exe not found` | 检查 `config/paraview.json` candidates；或设 `PARAVIEW_PVPYTHON` |
| `pvdata_import` 拒绝 3D 体积 | 属预期；换平面切片，或走 `pvdata_render_scatter3d` 点云渲染 |
| reader 打开失败 | 格式依赖第三方 codec 未装；换 `OpenDataFile` 可识别的常规格式 |
| 想测更多格式 | 在 `sample_data/` 放平面场样本后重跑 `--selftest` |
