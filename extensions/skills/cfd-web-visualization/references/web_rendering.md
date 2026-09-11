# Web 渲染引擎接口与载荷协议

核对日期：2026-09-10。适用源码：`extensions/mcp/cfd-npy3d/`。
本文件描述「CFD Web 可视化工作台」的 HTTP 端点、数据结构与产物约定。

## 1. 组成

| 位置 | 作用 |
|---|---|
| `extensions/mcp/cfd-npy3d/http_bridge.py` | HTTP 桥：既反射 MCP 工具为 OpenAPI，也托管 Web 工作台 |
| `extensions/mcp/cfd-npy3d/webviz.py` | 工作台后端纯函数层（格式/数据集/导入/载荷/论文导出） |
| `extensions/mcp/cfd-npy3d/webviewer/` | 前端静态资源（`launch.html` 弹出式启动页 / `index.html` / `viewer.js` / `viewer.css` / `formats.json`） |
| `extensions/mcp/cfd-npy3d/tools/npy3d_web_viewer.json` | 入口工具的契约（模型可调用） |

前端零外部依赖（原生 WebGL + Canvas），不访问 CDN，可离线使用。

## 2. HTTP 端点

`python extensions/mcp/cfd-npy3d/http_bridge.py --host 127.0.0.1 --port 8765`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/viewer` | 返回渲染引擎单页应用（与工作站统一的深色科研风 UI） |
| GET | `/viewer/launch` | 弹出式启动页：浏览器侧 `window.open` 弹出独立渲染新界面（被拦截时页内按钮手动打开） |
| GET | `/viewer/<asset>` | 前端静态资源（白名单后缀，禁止目录穿越；无后缀默认补 `.html`） |
| GET | `/api/formats` | 支持导入格式清单（读 `webviewer/formats.json`） |
| POST | `/api/datasets` | 扫描数据目录：`{data_dir?}` → `{data_dir, datasets[]}` |
| POST | `/api/import` | 导入数据文件 → 导入报告（见下） |
| POST | `/api/series` | 取某帧渲染载荷：`{dataset, frame?, channel?, max_points?}` |
| POST | `/api/export/paper` | 论文插图：`{image_b64|image_path, caption?, label?, width?}` |
| GET | `/files/<path>` | 静态服务产物 PNG/GIF（既有能力，聊天内嵌复用） |

CORS 允许 `*`；同源打开 `/viewer` 时前端直接同源调用 `/api/*`。

### 2.1 `/api/import` 请求体

| 字段 | 说明 |
|---|---|
| `file_path` | 服务器侧绝对路径（与 `filename`+`content_b64` 二选一） |
| `filename` + `content_b64` | 浏览器上传（`content_b64` 可为 `data:...;base64,` 形式） |
| `case` | 归档名（可选） |
| `array_name` | ParaView 文件的数组名（可选） |
| `time_slice` | 时间步 `0` / `0-4` / `all`（默认 `0`） |
| `sample_w` / `sample_h` | 非结构网重采样尺寸（默认长轴 320） |
| `convert` | 是否尝试把 x-y 平面 2D 场转成 X/Y/Q .npy（默认 `true`） |

返回：

```json
{ "ok": true, "origin": "upload|path", "kind": "npy|paraview",
  "file": "...", "work_dir": "...", "data_dir": "...", "converted": false,
  "message": "...", "next_tools": ["npy3d_inspect", "..."] }
```

### 2.2 `/api/series` 载荷

`kind="grid"`（.npy 数据集）：

```json
{ "kind": "grid", "dataset": "<dir>", "frame": 0, "frames": 12,
  "channel": 0, "channels": 3, "stride": 2, "grid": [H, W],
  "x": [...], "y": [...], "z": [...], "indices": [...],
  "value_range": [min, max], "axes": ["X","Y","Q"], "note": "..." }
```

`kind="points"`（ParaView 文件，需 pvpython）：

```json
{ "kind": "points", "dataset": "<file>", "frame": 0, "frames": 1,
  "channel": 0, "channels": 1, "points": [[x,y,z], ...], "value": [...],
  "value_range": [min, max], "axes": ["X","Y","Z"], "array_name": "...", "note": "..." }
```

约定：

- 所有数值均为 JSON 安全的有限数（NaN/Inf 已在后端剔除或压缩，三角形索引不引用无效点）；
- `indices` 仅在规则网格且三角形数不超过上限时给出，用于渲染曲面；否则前端以点云渲染；
- 大网格按 `stride` 抽样，默认点上限约 6 万（`CFD_WEB_MAX_POINTS` 语义见
  `webviz.DEFAULT_MAX_POINTS`）。

### 2.3 `/api/export/paper` 返回

```json
{ "image_path": "...", "url": "http://.../files/figures/xxx.png",
  "filename": "xxx.png", "caption": "...", "label": "...",
  "latex": "\\begin{figure}[t]\n  \\centering\n  \\includegraphics[width=\\linewidth]{figures/xxx.png}\n  \\caption{...}\n  \\label{fig:...}\n\\end{figure}" }
```

产物落在 `<产物根>/figures/`，与 `latex-paper` 插件的插图目录约定一致。

## 3. 产物与产物根

- 产物根：环境变量 `NPY3D_OUT_ROOT`，缺省为 `extensions/mcp/output`；
- 导入：`<产物根>/import/<case>/`，2D 场转换结果 `<产物根>/import/<case>/data/`；
- 论文插图：`<产物根>/figures/`；
- 对外基址：`CFD_BRIDGE_PUBLIC_BASE`（缺省 `http://<host>:<port>`）。

## 4. 本地验证

```powershell
cd extensions/mcp/cfd-npy3d
python http_bridge.py --host 127.0.0.1 --port 8765
# 弹出式入口（技能默认）：浏览器打开 http://127.0.0.1:8765/viewer/launch
# 渲染引擎本体：http://127.0.0.1:8765/viewer
```

CI 侧由 `tests/test_cfd_npy3d_webviz.py` 覆盖格式清单、数据集扫描、载荷 JSON 安全性、
导入与论文导出片段。
