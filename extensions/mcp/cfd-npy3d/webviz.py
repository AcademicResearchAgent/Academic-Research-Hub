# -*- coding: utf-8 -*-
"""webviz.py —— cfd-npy3d「Web 可视化工作台」后端（数据导入 + 实时渲染载荷 + 论文导出）。

面向「用户选中 npy3d / pvdata 可视化技能后，出现的数据导入功能入口 + 浏览器端
实时物理图像渲染引擎 + 可选的论文插图导出」这条链路，提供与 http_bridge.py 配套
的纯函数层（仅依赖标准库 + numpy，不引入 Web 框架）：

  1. load_formats()/supported_exts()/kind_of()  支持导入的格式清单；
  2. default_data_dir()/list_datasets()         数据集发现（npy 目录 / ParaView 文件）；
  3. import_file()/import_upload()              把支持格式的数据文件导入统一产物根；
  4. series_payload()                           把一帧切片转成 WebGL 前端可直接消费的载荷；
  5. export_paper()                             导出论文级 PNG + LaTeX figure 片段（可选）。

产物全部落在 registry.OUT_ROOT 之下（与既有 npy3d/pvdata 工具共用同一产物根），
因此 http_bridge 的 `/files/...` 静态服务与聊天内嵌展示可继续复用。
"""
from __future__ import annotations

import base64
import datetime
import json
import os
import re
import secrets
import shutil

import numpy as np

import core
import pvbridge
import registry

BASE = registry.BASE
OUT_ROOT = os.path.normpath(registry.OUT_ROOT)
VIEWER_DIR = os.path.join(BASE, "webviewer")
IMPORT_ROOT = os.path.join(OUT_ROOT, "import")
FIGURE_ROOT = os.path.join(OUT_ROOT, "figures")

DEFAULT_MAX_POINTS = 60000
MAX_SURFACE_TRIS = 900000


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def viewer_base() -> str:
    """Web 渲染引擎对外可访问基址（可用 CFD_BRIDGE_PUBLIC_BASE 覆盖）。"""
    env = os.environ.get("CFD_BRIDGE_PUBLIC_BASE")
    if env:
        return env.rstrip("/")
    return "http://127.0.0.1:%s" % os.environ.get("CFD_BRIDGE_PORT", "8765")


TOKEN_ENV = "CFD_BRIDGE_TOKEN"
TOKEN_FILE = os.path.join(OUT_ROOT, ".bridge_token")
_TOKEN_CACHE: str | None = None


def bridge_token() -> str:
    """技能与桥服务共享的访问令牌。

    渲染服务是「技能后端」而非可自由浏览的网站，因此查看器页面与 ``/api/*``
    只对携带本令牌的请求开放。MCP handler 与 http_bridge 是两个进程，这里用
    同一个函数取令牌：环境变量 ``CFD_BRIDGE_TOKEN`` 优先，否则落在产物根的
    隐藏文件 ``.bridge_token``（任一方先生成、另一方读取，重启后保持不变）。
    """
    global _TOKEN_CACHE
    if _TOKEN_CACHE:
        return _TOKEN_CACHE
    env = os.environ.get(TOKEN_ENV)
    if env:
        _TOKEN_CACHE = env
        return env
    try:
        with open(TOKEN_FILE, encoding="utf-8") as f:
            tok = f.read().strip()
        if tok:
            _TOKEN_CACHE = tok
            return tok
    except OSError:
        pass
    tok = secrets.token_urlsafe(24)
    tmp = "%s.tmp%d" % (TOKEN_FILE, os.getpid())
    try:
        os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(tok)
        os.replace(tmp, TOKEN_FILE)
    except OSError:
        pass
    _TOKEN_CACHE = tok
    return tok


def _with_token(url: str) -> str:
    """为入口 URL 追加技能共享令牌，使界面仅由技能调用开放，而非公开站点。"""
    from urllib.parse import urlencode
    sep = "&" if "?" in url else "?"
    return url + sep + urlencode({"t": bridge_token()})


def viewer_url(dataset: str | None = None, frame: int = 0, channel: int = 0,
               embed_in_paper: bool = False, popup: bool = False) -> str:
    """拼出带预选参数的工作台入口 URL。

    ``popup=True`` 时额外携带 ``popup=1``，查看器据此隐藏「弹出新窗口」按钮，
    避免在已弹出的独立窗口里重复弹出。
    """
    from urllib.parse import urlencode
    q = {"frame": int(frame), "channel": int(channel)}
    if dataset:
        q["dataset"] = dataset
    if embed_in_paper:
        q["paper"] = "1"
    if popup:
        q["popup"] = "1"
    return _with_token(viewer_base() + "/viewer?" + urlencode(q))


def launcher_url(dataset: str | None = None, frame: int = 0, channel: int = 0,
                 embed_in_paper: bool = False) -> str:
    """拼出弹出式启动页 URL（浏览器侧 window.open 弹出独立渲染新界面）。"""
    from urllib.parse import urlencode
    q = {"frame": int(frame), "channel": int(channel), "popup": "1"}
    if dataset:
        q["dataset"] = dataset
    if embed_in_paper:
        q["paper"] = "1"
    return _with_token(viewer_base() + "/viewer/launch?" + urlencode(q))


def entry_url(dataset: str | None = None, frame: int = 0, channel: int = 0,
              embed_in_paper: bool = False, open_in: str = "popup") -> str:
    """按打开方式给出技能入口 URL。

    ``open_in="popup"``（默认）走弹出式启动页，使用技能时弹出独立新界面；
    ``open_in="tab"`` 直接给出查看器 URL，在浏览器标签页中打开。
    """
    mode = str(open_in or "").strip().lower()
    if mode in ("popup", "window", "new_window", "new-window"):
        return launcher_url(dataset, frame, channel, embed_in_paper)
    return viewer_url(dataset, frame, channel, embed_in_paper)


def _f(v) -> float:
    v = float(v)
    return v if np.isfinite(v) else 0.0


def _sanitize(name) -> str:
    return core.sanitize_case(name)


# --------------------------------------------------------------------------- #
# 1. 支持格式清单（webviewer/formats.json 为单一事实源）
# --------------------------------------------------------------------------- #
def load_formats() -> dict:
    with open(os.path.join(VIEWER_DIR, "formats.json"), encoding="utf-8") as f:
        return json.load(f)


def format_groups() -> list:
    return load_formats().get("formats", [])


def supported_exts() -> list:
    exts = []
    for g in format_groups():
        for e in g.get("ext", []):
            e = e.lower()
            if e not in exts:
                exts.append(e)
    return exts


def kind_of(path: str) -> str | None:
    """按扩展名判定导入类别（'npy' / 'paraview'），不支持返回 None。"""
    low = (path or "").lower()
    if os.path.isdir(path):
        return "npy"
    for g in format_groups():
        for e in g.get("ext", []):
            if low.endswith(e.lower()):
                return g.get("kind")
    return None


# --------------------------------------------------------------------------- #
# 2. 数据集发现
# --------------------------------------------------------------------------- #
def default_data_dir() -> str:
    env = os.environ.get("CFD_DATA_DIR")
    if env and os.path.isdir(env):
        return env
    proj = os.path.join(registry.WORKSPACE, "exp_data")
    if os.path.isdir(proj):
        return proj
    return proj


def _npy_dirs(data_dir: str) -> list:
    out = []
    for root, dirs, files in os.walk(data_dir):
        dirs[:] = [d for d in dirs if not d.startswith((".", "_"))]
        blob = " ".join(f.lower() for f in files)
        if any(m in blob for m in ("x.npy", "y.npy", "q.npy")):
            out.append(root)
    return out


def _rel_label(path: str, root: str) -> str:
    rel = os.path.relpath(path, root)
    return os.path.basename(path) if rel in (".", "") else rel


def _paraview_files(data_dir: str) -> list:
    pv_ext = tuple(e for e in supported_exts() if e != ".npy")
    rows = []
    for root, dirs, files in os.walk(data_dir):
        dirs[:] = [d for d in dirs if not d.startswith((".", "_"))]
        for fn in sorted(files):
            if fn.lower().endswith(pv_ext):
                rows.append(os.path.join(root, fn))
    return rows


def _scan_roots(data_dir: str | None = None) -> list:
    """待扫描的数据目录：显式给定则只用它；否则合并默认目录与导入产物根。"""
    if data_dir:
        return [data_dir]
    roots = [default_data_dir()]
    if os.path.isdir(IMPORT_ROOT):
        key = os.path.normcase(os.path.normpath(IMPORT_ROOT))
        if all(key != os.path.normcase(os.path.normpath(r)) for r in roots):
            roots.append(IMPORT_ROOT)
    return roots


def list_datasets(data_dir: str | None = None) -> list:
    """列出可导入/可渲染的数据集（npy 目录 + ParaView 文件）。

    未显式给 data_dir 时，同时扫描默认数据目录与导入产物根（IMPORT_ROOT），
    使「数据导入」入口落盘的数据集可直接出现在列表中。
    """
    rows: list = []
    seen: set = set()
    for dd in _scan_roots(data_dir):
        if not dd or not os.path.isdir(dd):
            continue
        for d in _npy_dirs(dd):
            key = os.path.normcase(os.path.normpath(d))
            if key in seen:
                continue
            seen.add(key)
            rel = _rel_label(d, dd)
            item = {"id": d, "kind": "npy", "label": rel, "path": d,
                    "renderable": True, "frames": 1, "channels": 1,
                    "grid": None, "note": ""}
            try:
                ds = core.open_dataset(d)
                item.update(frames=ds.T, channels=ds.C, grid=[ds.H, ds.W])
                item["label"] = "%s  (T=%d, C=%d, grid=%dx%d)" % (rel, ds.T, ds.C, ds.H, ds.W)
            except Exception as e:                          # noqa: BLE001
                item["renderable"] = False
                item["note"] = str(e)
            rows.append(item)
        for full in _paraview_files(dd):
            key = os.path.normcase(os.path.normpath(full))
            if key in seen:
                continue
            seen.add(key)
            rows.append({"id": full, "kind": "paraview",
                         "label": _rel_label(full, dd), "path": full,
                         "renderable": True, "frames": None, "channels": None,
                         "grid": None,
                         "note": "点云/网格（需 ParaView 读取）"})
    return rows


def resolve_dataset(dataset: str | None, data_dir: str | None = None) -> str:
    """把 dataset 参数解析成真实路径：先当路径，再按 label/文件名在 data_dir 中匹配。"""
    if dataset:
        cand = os.path.normpath(os.path.expanduser(dataset))
        if os.path.exists(cand):
            return cand
        for it in list_datasets(data_dir):
            if dataset in (it["id"], it["label"], os.path.basename(it["path"])):
                return it["path"]
        raise FileNotFoundError("找不到数据集: %s" % dataset)
    rows = [it for it in list_datasets(data_dir) if it.get("renderable")]
    if not rows:
        raise FileNotFoundError("数据目录中没有可渲染数据集: %s"
                                % (data_dir or default_data_dir()))
    return rows[0]["path"]


# --------------------------------------------------------------------------- #
# 3. 数据文件导入
# --------------------------------------------------------------------------- #
def _slug(text: str, fallback: str = "imported") -> str:
    s = os.path.splitext(os.path.basename(str(text or "")))[0]
    s = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", s).strip("_")
    return s or fallback


def _unique_dir(parent: str, name: str) -> str:
    target = os.path.join(parent, name)
    if not os.path.exists(target):
        return target
    i = 1
    while os.path.exists("%s_%d" % (target, i)):
        i += 1
    return "%s_%d" % (target, i)


def _write_upload(filename: str, content_b64: str, dest_dir: str) -> str:
    os.makedirs(dest_dir, exist_ok=True)
    name = os.path.basename(str(filename or "upload.bin").replace("\\", "/"))
    if not name:
        name = "upload.bin"
    raw = base64.b64decode(content_b64 or "")
    path = os.path.join(dest_dir, name)
    with open(path, "wb") as f:
        f.write(raw)
    return path


def import_file(file_path: str | None = None, filename: str | None = None,
                content_b64: str | None = None, case: str | None = None,
                array_name: str | None = None, time_slice: str = "0",
                sample_w: int = 0, sample_h: int = 0,
                convert: bool = True) -> dict:
    """导入一个「支持格式」的数据文件到产物根，供 Web 渲染引擎读取。

    - npy 类：把单个 .npy 拷入 `<IMPORT_ROOT>/<case>/`；当该目录集齐 X/Y/Q 时
      即可作为 npy3d 数据集渲染（缺失字段会在报告里说明）。
    - ParaView 类：拷贝原文件；对可能是 x-y 平面 2D 场的文件（convert=True 且
      本机有 pvpython）尝试用 import2d 转成 X/Y/Q .npy，失败则退化为点云渲染。

    返回 dict（供工具层渲染 markdown / 供 HTTP 层直接 JSON 化）。
    """
    case = _sanitize(case) if case else None
    stem_src = filename or file_path or "imported"
    # 显式给 case 时复用同名目录，便于把 X/Y/Q 分次导入同一数据集目录；
    # 未给 case 时按文件名建唯一目录，避免互相覆盖。
    work = os.path.join(IMPORT_ROOT, case) if case else _unique_dir(IMPORT_ROOT, _slug(stem_src))
    os.makedirs(work, exist_ok=True)

    if content_b64:
        path = _write_upload(filename or stem_src, content_b64, work)
        origin = "upload"
    elif file_path:
        if not os.path.isfile(file_path):
            raise FileNotFoundError("文件不存在: %s" % file_path)
        path = os.path.join(work, os.path.basename(file_path))
        if os.path.abspath(file_path) != os.path.abspath(path):
            shutil.copy2(file_path, path)
        origin = "path"
    else:
        raise ValueError("必须提供 file_path 或（filename + content_b64）之一")

    kind = kind_of(path)
    report = {"ok": False, "origin": origin, "kind": kind,
              "file": path, "work_dir": work, "data_dir": None,
              "converted": False, "message": "", "next_tools": []}

    if kind is None:
        report["message"] = ("不支持的扩展名: `%s`（支持 %s）"
                             % (os.path.basename(path), ", ".join(supported_exts())))
        return report

    if kind == "npy":
        have = sorted(f for f in os.listdir(work) if f.lower().endswith(".npy"))
        roles = [r for r in ("x", "y", "q") if any(r in f.lower() for f in have)]
        if len(roles) == 3:
            report.update(ok=True, data_dir=work,
                          message="npy 数据集就绪（X/Y/Q 齐备），可直接渲染。")
        else:
            report["message"] = ("已拷入 `.npy`，但目录内缺少 %s 字段；"
                                 "请把同一数据集的 X/Y/Q .npy 一起导入该目录。"
                                 % ", ".join(r.upper() for r in ("x", "y", "q")
                                             if r not in roles))
        report["next_tools"] = _next_tools(report["data_dir"] or work)
        return report

    # kind == paraview
    report["message"] = "已导入 ParaView 文件（按点云/网格渲染）。"
    report["ok"] = True
    report["next_tools"] = ["pvdata_inspect", "pvdata_render_scatter3d",
                            "pvdata_render_animation"]
    if convert and path.lower().endswith((".vtk", ".vti", ".vtu", ".vts",
                                          ".vtr", ".ex2", ".xdmf", ".xmf")):
        if pvbridge.available():
            out_dir = os.path.join(work, "data")
            try:
                res = pvbridge.run_job("import2d", {
                    "file_path": path, "array_name": array_name,
                    "time_slice": time_slice, "sample_w": int(sample_w or 0),
                    "sample_h": int(sample_h or 0), "out_dir": out_dir})
                report.update(converted=True, data_dir=res.get("out_dir", out_dir),
                              message="已把 x-y 平面 2D 场转换为 X/Y/Q .npy，"
                                      "可作为 npy3d 数据集渲染规则曲面/动画。")
                report["next_tools"] = _next_tools(report["data_dir"])
            except Exception as e:                          # noqa: BLE001
                report["message"] = ("导入成功；自动转换为 2D 平面场失败"
                                     "（多为 z 向有厚度的真三维场），"
                                     "请按点云渲染: %s" % str(e)[:200])
            finally:
                pvbridge.clean_run_dir()
        else:
            report["message"] = "导入成功；本机未配置 pvpython，仅提供点云/网格渲染。"
    return report


def _next_tools(data_dir: str) -> list:
    return ["npy3d_inspect", "npy3d_render_surface", "npy3d_render_animation",
            "npy3d_web_viewer"]


# --------------------------------------------------------------------------- #
# 4. 浏览器渲染载荷
# --------------------------------------------------------------------------- #
def _grid_indices(h: int, w: int, valid: np.ndarray) -> np.ndarray:
    """在有效点掩码上生成三角形索引（无效点不引用，避免 NaN 撕裂）。"""
    ids = -np.ones(h * w, dtype=np.int64)
    ids[valid.ravel()] = np.arange(int(valid.sum()), dtype=np.int64)
    gid = ids.reshape(h, w)
    a, b = gid[:-1, :-1].ravel(), gid[:-1, 1:].ravel()
    c, d = gid[1:, :-1].ravel(), gid[1:, 1:].ravel()
    m1 = (a >= 0) & (b >= 0) & (c >= 0)
    m2 = (b >= 0) & (d >= 0) & (c >= 0)
    tri = np.concatenate([
        np.stack([a[m1], b[m1], c[m1]], axis=1),
        np.stack([b[m2], d[m2], c[m2]], axis=1)])
    return tri.ravel().astype(np.int64)


def _npy_payload(data_dir: str, frame: int, channel: int,
                 max_points: int) -> dict:
    ds = core.open_dataset(data_dir)
    t = int(np.clip(frame, 0, max(ds.T - 1, 0)))
    c = int(np.clip(channel, 0, max(ds.C - 1, 0)))
    X = np.asarray(ds.X, dtype=np.float64)
    Y = np.asarray(ds.Y, dtype=np.float64)
    Z = np.asarray(ds.load_q_frame(t, c), dtype=np.float64)
    h0, w0 = X.shape
    stride = max(1, int(np.ceil(np.sqrt(h0 * w0 / float(max(max_points, 1))))))
    sl = (slice(None, None, stride), slice(None, None, stride))
    x, y, z = X[sl].ravel(), Y[sl].ravel(), Z[sl].ravel()
    valid = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    if not valid.any():
        raise ValueError("该帧/通道全为 NaN，无有效点可渲染")
    xs, ys, zs = x[valid], y[valid], z[valid]
    h, w = X[sl].shape
    vmin, vmax = _f(np.min(zs)), _f(np.max(zs))
    payload = {
        "kind": "grid",
        "dataset": data_dir,
        "frame": t, "frames": ds.T,
        "channel": c, "channels": ds.C,
        "stride": stride, "grid": [h, w],
        "x": xs.tolist(), "y": ys.tolist(), "z": zs.tolist(),
        "value_range": [vmin, vmax],
        "axes": ["X", "Y", "Q"],
        "note": ("grid %dx%d, stride=%d → %d points"
                 % (h0, w0, stride, int(valid.sum()))),
    }
    tris = (h - 1) * (w - 1) * 6
    if h > 1 and w > 1 and tris <= MAX_SURFACE_TRIS:
        payload["indices"] = _grid_indices(h, w, valid.reshape(h, w)).tolist()
    return payload


def _pv_payload(file_path: str, array_name: str | None, frame: int,
                max_points: int) -> dict:
    pvbridge.find_pvpython()
    npz = pvbridge.scratch_npz()
    try:
        res = pvbridge.run_job("points", {
            "file_path": file_path, "array_name": array_name,
            "timestep_index": int(frame), "max_points": int(max_points),
            "out_npz": npz})
        pts, val = core.load_npz_points(npz)
    finally:
        pvbridge.clean_run_dir()
    finite = np.isfinite(pts).all(axis=1) & np.isfinite(val)
    pts, val = pts[finite], val[finite]
    if len(pts) == 0:
        raise ValueError("该时间步没有有限点可渲染")
    return {
        "kind": "points",
        "dataset": file_path,
        "frame": int(res.get("timestep_index", frame)),
        "frames": int(res.get("timestep_count") or 1),
        "channel": 0, "channels": 1,
        "points": pts.tolist(), "value": val.tolist(),
        "value_range": [_f(np.min(val)), _f(np.max(val))],
        "axes": ["X", "Y", "Z"],
        "array_name": res.get("array_name"),
        "note": ("points %s/%s (sampled)"
                 % (res.get("npts_saved"), res.get("npts_orig"))),
    }


def series_payload(dataset: str | None = None, frame: int = 0, channel: int = 0,
                   max_points: int = DEFAULT_MAX_POINTS,
                   data_dir: str | None = None) -> dict:
    """把数据集的一帧转成前端渲染载荷（JSON 安全：无 NaN/Inf）。"""
    path = resolve_dataset(dataset, data_dir)
    max_points = int(max_points or DEFAULT_MAX_POINTS)
    if os.path.isdir(path):
        return _npy_payload(path, frame, channel, max_points)
    if path.lower().endswith(".npy"):
        return _npy_payload(os.path.dirname(path), frame, channel, max_points)
    return _pv_payload(path, None, frame, max_points)


# --------------------------------------------------------------------------- #
# 5. 论文插图导出（可选）
# --------------------------------------------------------------------------- #
def export_paper(image_b64: str | None = None, image_path: str | None = None,
                 caption: str = "", label: str = "", name: str | None = None,
                 width: str = "\\linewidth", case: str | None = None) -> dict:
    """把渲染引擎当前帧存为论文级 PNG，并给出可直接粘贴的 LaTeX figure 片段。"""
    os.makedirs(FIGURE_ROOT, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = _sanitize(name) if name else "physics_render_%s" % ts
    if not stem.lower().endswith(".png"):
        stem += ".png"
    out_path = core._unique_path(os.path.join(FIGURE_ROOT, stem))

    if image_b64:
        payload = image_b64.split(",", 1)[-1]
        with open(out_path, "wb") as f:
            f.write(base64.b64decode(payload))
    elif image_path:
        if not os.path.isfile(image_path):
            raise FileNotFoundError("图片不存在: %s" % image_path)
        shutil.copy2(image_path, out_path)
    else:
        raise ValueError("必须提供 image_b64（前端截帧）或 image_path（已有 PNG）")

    fig_label = label or os.path.splitext(os.path.basename(out_path))[0]
    rel = os.path.relpath(out_path, OUT_ROOT).replace(os.sep, "/")
    cap = caption or "Physics field rendered from CFD data."
    latex = "\n".join([
        "\\begin{figure}[t]",
        "  \\centering",
        "  \\includegraphics[width=%s]{%s}" % (width, rel),
        "  \\caption{%s}" % cap,
        "  \\label{fig:%s}" % fig_label,
        "\\end{figure}",
    ])
    return {
        "image_path": out_path,
        "url": viewer_base() + "/files/" + rel,
        "filename": os.path.basename(out_path),
        "caption": cap,
        "label": fig_label,
        "latex": latex,
    }
