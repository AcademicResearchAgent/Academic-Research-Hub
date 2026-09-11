# ParaView 集成配置（cfd_npy3d 扩展 / pvdata_*）

核对日期：2026-09-08。本文说明 ParaView 工作所需的全部配置如何在 Academic-Research-Hub（下称 ARH）内集中管理：
pvpython 定位、reader 支持清单、`pvdata_import` 导入链路，以及本地验证方式。

## 1. 涉及位置总览

```text
extensions/mcp/cfd-npy3d/
├── server.py                    MCP stdio 入口（注册 8 个工具）
├── pvbridge.py                  读 config/paraview.json 定位 pvpython + 执行 job（普通 Python 侧）
├── pvjob_pvdata.py              pvpython 侧 job 执行器（inspect / points / import2d）
├── webviz.py                    Web 工作台后端（格式清单 / 数据集 / 导入 / 渲染载荷 / 论文导出）
├── http_bridge.py               OpenAPI 工具桥 + /viewer 与 /api/* 端点
├── webviewer/                   前端静态资源（原生 WebGL 渲染引擎，零外部依赖）
│   ├── launch.html              弹出式启动页（技能默认入口，弹出独立渲染新界面）
│   ├── index.html               工作台单页（数据导入入口 + 渲染视口 + 参数面板）
│   ├── viewer.js                WebGL 渲染器 + 交互 + 论文导出
│   ├── viewer.css               深色科研风统一视觉令牌（查看器与启动页共用）
│   └── formats.json             ★ 支持导入格式清单（单一事实源，前后端共用）
├── config/
│   ├── paraview.json            ★ pvpython 定位与 job 超时（本机可改）
│   └── paraview_readers.json    ★ ParaView reader 类名 + 常见扩展名映射（自动生成）
├── checks/
│   ├── check_registry_consistency.py   契约一致性质量门
│   └── export_paraview_readers.py      （重新）枚举 reader 清单
├── skills/pvdata_visualization/ 点云着色 / 动画技能
├── skills/pvdata_import/        导入 ParaView 任意类型 2D 数据为 X/Y/Q 技能
├── skills/web_visualization/    Web 工作台技能（导入 + 实时渲染 + 论文插图）
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

## 6. Web 可视化工作台（数据导入 + 实时渲染 + 论文插图）

在既有「生成静态 PNG/GIF」之外，新增一条浏览器内**交互式实时渲染**链路。选中的数据文件
先在渲染引擎里实时观测（旋转/缩放/平移、切时间帧、换物理量通道、换色图、调颜色范围），
再由用户按需选择是否导出为论文插图——**导出这一步完全可选**，不启用则不产生论文产物。

### 6.1 组成

| 位置 | 作用 |
| --- | --- |
| `webviz.py` | 后端纯函数层：格式清单、数据集扫描、数据导入、渲染载荷、论文导出、入口 URL |
| `http_bridge.py` | 托管 `/viewer`、`/viewer/launch` 与 `/api/*` 数据面（CORS `*`，零 Web 框架） |
| `webviewer/` | 前端：原生 WebGL + Canvas，**零外部 CDN**，可离线使用 |
| `tools/npy3d_web_viewer.json` | 入口工具契约（模型可调用，含 `open_in` 打开方式） |
| `skills/web_visualization/` | 工作台技能（Hermes 名 `cfd-web-visualization`） |

入口风格：技能默认以 `open_in="popup"` 返回弹出式启动页，浏览器侧弹出独立渲染新界面；
渲染界面与工作站保持同一套深色科研风 UI（共享 `viewer.css` 视觉令牌与中文产品文案），
窗口尺寸/缩放/视角独立保持，可与工作站界面并行观测。

### 6.2 端点

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/viewer` | 渲染引擎单页（与工作站统一的深色科研风 UI） |
| GET | `/viewer/launch` | 弹出式启动页（弹出独立渲染新界面；被拦截时页内按钮打开） |
| GET | `/viewer/<asset>` | 前端静态资源（白名单后缀，防目录穿越；无后缀默认补 `.html`） |
| GET | `/api/formats` | 支持导入格式（读 `webviewer/formats.json`） |
| POST | `/api/datasets` | 扫描数据目录 → 数据集清单 |
| POST | `/api/import` | 导入支持格式文件（上传 base64 或服务器路径） |
| POST | `/api/series` | 取某帧渲染载荷（自动降采样、剔除 NaN） |
| POST | `/api/export/paper` | 截图 → 论文级 PNG + LaTeX `figure` 片段（用户可选） |
| GET | `/files/<path>` | 静态服务产物 PNG/GIF（既有能力，聊天内嵌复用） |

### 6.3 启动与自测

```powershell
# 启动工作台：弹出式入口 http://127.0.0.1:8765/viewer/launch（技能默认）
#             渲染引擎本体 http://127.0.0.1:8765/viewer
python extensions/mcp/cfd-npy3d/http_bridge.py --host 127.0.0.1 --port 8765

# 工作台回归测试（格式/扫描/载荷 JSON 安全/导入/论文导出/入口工具）
python -m unittest discover -s tests -p test_cfd_npy3d_webviz.py -v
```

跨机访问时用 `CFD_BRIDGE_PUBLIC_BASE` 指定对外基址；产物根仍由 `NPY3D_OUT_ROOT` 控制
（导入落 `import/<case>/`，论文插图落 `figures/`）。

### 6.4 支持导入的格式

- **X/Y/Q .npy 平面场**：同一目录含 `X.npy` / `Y.npy` / `Q.npy`，Q 布局
  `(H,W)/(C,H,W)/(T,H,W)/(T,C,H,W)`；也可分次导入（显式传 `case` 复用同一目录）；
- **ParaView 常见格式**：`.vtk .vtu .vti .vts .vtr .vtp .ex2 .vtm .pvd .xdmf .xmf .stl .ply .obj .csv`，
  x-y 平面 2D 场自动尝试转 X/Y/Q .npy 规则曲面，其余按三维点云渲染。

清单以 `webviewer/formats.json` 为单一事实源，前后端共用。

## 7. 常见问题

| 现象 | 处理 |
| --- | --- |
| `pvpython.exe not found` | 检查 `config/paraview.json` candidates；或设 `PARAVIEW_PVPYTHON` |
| `pvdata_import` 拒绝 3D 体积 | 属预期；换平面切片，或走 `pvdata_render_scatter3d` 点云渲染 |
| reader 打开失败 | 格式依赖第三方 codec 未装；换 `OpenDataFile` 可识别的常规格式 |
| 想测更多格式 | 在 `sample_data/` 放平面场样本后重跑 `--selftest` |
| 工作台打不开 / 入口 URL 无响应 | 先启动 `http_bridge.py`；跨机访问设 `CFD_BRIDGE_PUBLIC_BASE` |
| 工作台导入后仍是点云 | 该文件 z 向有厚度（真三维场）或本机无 pvpython；属预期降级 |
| 大网格渲染卡顿 | 载荷默认降采样到约 6 万点；换更粗网格或减小数据规模 |
