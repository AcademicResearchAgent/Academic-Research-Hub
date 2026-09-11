# -*- coding: utf-8 -*-
"""handlers.py —— cfd_npy3d_mcp 七个 MCP 工具的实现层。

每个工具一个显式 Python 函数（带完整签名），与 tools/<name>.json 的
参数契约一一对应；server 启动时按 registry 把这里注册进 FastMCP。
函数签名、默认值与行为保持与「1.1.0 时代码内嵌版本」完全一致，
避免注册方式变化引入回归。内部辅助（_pv_require/_fmt_*/_points_common）
为本模块私有。
"""
from __future__ import annotations

import os
import re

import core
import pvbridge
import registry
import webviz

OUT_ROOT = registry.OUT_ROOT
SAMPLE_DIR = core.SAMPLE_DIR


def npy3d_inspect(data_dir: str | None = None) -> str:
    """检视 X/Y/Q .npy CFD 数据集，返回 Markdown 报告（见工具契约描述）。"""
    dd = data_dir or SAMPLE_DIR
    ds = core.open_dataset(dd)
    return ds.inspect_md()


def npy3d_render_surface(
    data_dir: str | None = None,
    frame: int = 0,
    channels: str = "0",
    case: str | None = None,
    azim: int = -60,
    elev: int = 35,
) -> str:
    """对 X/Y/Q .npy CFD 数据把某一帧的物理量场画成三维曲面图并保存 PNG。"""
    dd = data_dir or SAMPLE_DIR
    ds = core.open_dataset(dd)
    r = core.render_surface(ds, frame=frame, channels=channels, case=case,
                            out_root=OUT_ROOT, azim=azim, elev=elev)
    return r["md"]


def npy3d_render_animation(
    data_dir: str | None = None,
    channel: int = 0,
    case: str | None = None,
    max_frames: int = 48,
    fps: int = 6,
) -> str:
    """把某通道沿时间帧逐帧重建三维曲面并存为 GIF 动画。"""
    dd = data_dir or SAMPLE_DIR
    ds = core.open_dataset(dd)
    r = core.render_animation(ds, channel=channel, case=case, out_root=OUT_ROOT,
                              max_frames=max_frames, fps=fps)
    return r["md"]


def _pv_require() -> str:
    return pvbridge.find_pvpython()


def _fmt_range(r):
    return "[%.4g, %.4g]" % (r[0], r[1]) if len(r) >= 2 else str(r)


def _fmt_arrays(lst, kind):
    if not lst:
        return "- %s: (无)\n" % kind
    lines = ["**%s** (%d):" % (kind, len(lst))]
    for a in lst:
        lines.append("- `%s`  comps=%d  range=%s" %
                     (a["name"], a["components"],
                      _fmt_range(a["ranges"][0]) if a["ranges"] else "?"))
    return "\n".join(lines)


def pvdata_inspect(file_path: str) -> str:
    """检视任意 ParaView 可读文件：reader/包围盒/点数/时间步/数组清单。"""
    _pv_require()
    res = pvbridge.run_job("inspect", {"file_path": file_path})
    b = res.get("bounds")
    lines = [
        "## pvdata 检视: `%s`" % os.path.basename(file_path),
        "",
        "- reader: `%s`" % res.get("reader", "?"),
        "- bounds: %s" % ("[%.4g, %.4g, %.4g, %.4g, %.4g, %.4g]" % tuple(b)
                          if b else "N/A"),
        "- points: %s   cells: %s" % (res.get("points"), res.get("cells")),
    ]
    ts = res.get("timesteps") or []
    if ts:
        lines.append("- timesteps: %d 个，范围 [%.6g, %.6g]，前 8 个 %s"
                     % (len(ts), ts[0], ts[-1], [round(t, 4) for t in ts[:8]]))
    else:
        lines.append("- timesteps: 无（静态数据）")
    lines += ["", _fmt_arrays(res.get("point_arrays", []), "点数组 (POINT_DATA)"),
              "", _fmt_arrays(res.get("cell_arrays", []), "单元数组 (CELL_DATA)"),
              "", "**下一步**: 用 `pvdata_render_scatter3d(file_path=..., "
              "array_name=...)` 画三维点云着色图。"]
    return "\n".join(lines)


def _points_common(file_path, array_name, timestep_index, max_points):
    """跑一次 points job，返回 (res, pts, val)。"""
    npz = pvbridge.scratch_npz()
    res = pvbridge.run_job("points", {
        "file_path": file_path, "array_name": array_name,
        "timestep_index": timestep_index, "max_points": max_points,
        "out_npz": npz})
    pts, val = core.load_npz_points(npz)
    return res, pts, val


def pvdata_render_scatter3d(
    file_path: str,
    array_name: str | None = None,
    timestep_index: int = 0,
    max_points: int = 250000,
    case: str | None = None,
    azim: int = -55,
    elev: int = 25,
    cmap: str = "coolwarm",
) -> str:
    """读取任一 ParaView 文件某时间步的点 + 数组，画三维散点着色图 PNG。"""
    _pv_require()
    try:
        res, pts, val = _points_common(file_path, array_name, timestep_index,
                                       max_points)
        tl = ("t=%g (step %d/%d)" % (res["time"], res["timestep_index"],
                                     res["timestep_count"] - 1)
              if res.get("timestep_count") else None)
        tag = "pvdata_" + "".join(
            c if c.isalnum() else "_" for c in str(res["array_name"]))[:24]
        r = core.render_point_cloud(pts, val, res["array_name"], OUT_ROOT,
                                    case=case, azim=azim, elev=elev, cmap=cmap,
                                    tag=tag, time_label=tl,
                                    npts_orig=res["npts_orig"])
    finally:
        pvbridge.clean_run_dir()
    extra = "\n".join([
        "- association=%s  components=%d" % (res["association"],
                                             res["components"]),
        "- 采样前点数=%d → 保存 %d" % (res["npts_orig"], res["npts_saved"]),
        "- 跳过不含该数组的块数=%d  非有限剔除=%d" %
        (res["skipped_blocks"], res["filtered_nonfinite"]),
        "- reader: `%s`" % res["reader"]])
    return r["md"] + "\n" + extra


def pvdata_render_animation(
    file_path: str,
    array_name: str | None = None,
    max_frames: int = 24,
    max_points: int = 120000,
    fps: int = 6,
    case: str | None = None,
) -> str:
    """对含时间步的 ParaView 文件逐时间步生成三维点云着色 GIF 动画。"""
    _pv_require()
    meta = pvbridge.run_job("inspect", {"file_path": file_path})
    ts = meta.get("timesteps") or []
    if not ts:
        raise RuntimeError("文件没有时间步：%s（静态数据请用 pvdata_render_scatter3d）"
                           % file_path)
    import numpy as np
    idx = np.unique(np.linspace(0, len(ts) - 1, min(max_frames, len(ts)))
                    .astype(int)).tolist()
    frames, labels = [], []
    try:
        for i in idx:
            res, pts, val = _points_common(file_path, array_name, i, max_points)
            frames.append((pts, val))
            labels.append("t=%g" % res["time"] if res.get("time") is not None
                          else "step %d" % i)
        arr_name = res["array_name"]
        r = core.render_point_cloud_animation(frames, arr_name, OUT_ROOT,
                                              case=case, fps=fps,
                                              tag="pvdata_anim",
                                              time_labels=labels)
    finally:
        pvbridge.clean_run_dir()
    return r["md"]


def _sanitize(name) -> str:
    s = re.sub(r"[^0-9A-Za-z_\-]+", "_", str(name or ""))
    return s.strip("_") or "pvdata"


def pvdata_import(
    file_path: str,
    array_name: str | None = None,
    time_slice: str = "0",
    sample_w: int = 0,
    sample_h: int = 0,
    case: str | None = None,
) -> str:
    """把 ParaView 可读文件中 x-y 平面的 2D 场导入为 X/Y/Q .npy。"""
    _pv_require()
    if case:
        out_dir = os.path.join(OUT_ROOT, "cases", _sanitize(case), "data")
    else:
        stem = _sanitize(os.path.splitext(os.path.basename(file_path))[0])
        out_dir = os.path.join(OUT_ROOT, "import", stem, "data")
    try:
        res = pvbridge.run_job("import2d", {
            "file_path": file_path, "array_name": array_name,
            "time_slice": time_slice, "sample_w": int(sample_w or 0),
            "sample_h": int(sample_h or 0), "out_dir": out_dir})
    finally:
        pvbridge.clean_run_dir()
    b = res.get("bounds")
    nf = res.get("frames", 1)
    lines = [
        "## pvdata 导入为 X/Y/Q: `%s`" % os.path.basename(file_path),
        "",
        "- reader: `%s`" % res.get("reader", "?"),
        "- array: `%s`   association=%s   components=%d"
        % (res["array_name"], res["association"], res.get("components", 1)),
        "- 采样方式: %s" % res.get("method", "?"),
        "- 网格: W=%s, H=%s（npy 布局 (H,W)；多帧时为 (T,H,W)）"
        % (res.get("W"), res.get("H")),
        "- 帧数: %d（时间索引 %s）" % (nf, res.get("time_indices")),
        "- 首帧 NaN 占比: %.2f%%" % res.get("nan_percent", 0.0),
        "- bounds: %s" % ("[%.4g, %.4g, %.4g, %.4g, %.4g, %.4g]" % tuple(b)
                          if b else "N/A"),
        "- 产物目录 (data_dir): `%s`" % res.get("out_dir"),
        "  - `X.npy` `Y.npy` `Q.npy`（%s）" % ", ".join(res.get("files", [])),
        "",
        "**下一步**: 把 data_dir 直接交给 npy3d 工具渲染规则网格曲面/动画 ——",
        "- `npy3d_inspect(data_dir=\"%s\")`" % res.get("out_dir"),
        "- `npy3d_render_surface(data_dir=\"%s\", frame=%d, channels=\"0\", case=...)`"
        % (res.get("out_dir"), max(0, nf - 1)),
        "- `npy3d_render_animation(data_dir=\"%s\", channel=0, max_frames=48, fps=6)`"
        % res.get("out_dir"),
    ]
    return "\n".join(lines)


def npy3d_web_viewer(
    data_dir: str | None = None,
    file_path: str | None = None,
    dataset: str | None = None,
    frame: int = 0,
    channel: int = 0,
    embed_in_paper: bool = False,
    open_in: str = "popup",
) -> str:
    """Web 可视化工作台入口：数据导入 + 实时渲染引擎 +（可选）论文插图导出。"""
    lines = ["## Web 可视化工作台（数据导入 + 实时渲染 + 论文插图）", ""]

    report = None
    if file_path:
        report = webviz.import_file(file_path=file_path, convert=True)
        lines += ["### 导入结果", "",
                  "- 文件: `%s`" % report["file"],
                  "- 类别: **%s**%s" % (report["kind"], "（已转 X/Y/Q .npy）"
                                        if report.get("converted") else ""),
                  "- 说明: %s" % report.get("message", "")]
        if report.get("data_dir"):
            lines.append("- data_dir: `%s`" % report["data_dir"])
        lines.append("")

    preset = report.get("data_dir") if report else dataset
    url = webviz.entry_url(preset, frame, channel, embed_in_paper, open_in)
    popup = str(open_in or "").strip().lower() != "tab"
    lines += ["### 打开渲染引擎", "",
              "**入口**: %s" % url,
              "",
              ("**打开方式**: 弹出独立渲染新界面（浏览器侧弹窗；若被拦截请在启动页点击"
               "「打开渲染新界面」）" if popup
               else "**打开方式**: 在浏览器标签页中打开"),
              "",
              "> 渲染新界面与工作站同一套深色科研风 UI，打开后可：旋转/缩放/平移、拖动时间帧、"
              "切换物理量通道与色图、调颜色范围；左侧「数据导入」可继续上传或按路径导入"
              "支持格式的数据文件；顶栏「弹出新窗口」可再开一个独立窗口并行对照。",
              ""]

    try:
        rows = webviz.list_datasets(data_dir)
    except Exception as e:                                   # noqa: BLE001
        rows = []
        lines.append("（数据集扫描失败：%s）" % e)
    if rows:
        lines += ["### 已发现数据集（点击列表即可渲染）", "",
                  "| 类型 | 名称 | 帧/通道 | 网格 |",
                  "| --- | --- | --- | --- |"]
        for it in rows:
            fr = "%s / %s" % (it.get("frames"), it.get("channels"))
            grid = "x".join(str(v) for v in (it.get("grid") or [])) or "-"
            flag = "" if it.get("renderable") else "（不可渲染：%s）" % it.get("note", "")
            lines.append("| %s | `%s` %s | %s | %s |"
                         % (it["kind"], it["label"], flag, fr, grid))
        lines.append("")
    else:
        lines += ["### 已发现数据集", "",
                  "（`%s` 下暂无数据集，请先用左侧「数据导入」或传 `file_path` 导入）"
                  % (data_dir or webviz.default_data_dir()), ""]

    lines += ["### 支持的导入格式", "", "| 扩展名 | 说明 |", "| --- | --- |"]
    for g in webviz.format_groups():
        lines.append("| `%s` | %s |" % (" ".join(g["ext"]), g.get("note") or g["label"]))
    lines += ["", "### 下一步", "",
              "- 渲染规则曲面/动画：`npy3d_render_surface` / `npy3d_render_animation`",
              "- 渲染三维点云：`pvdata_render_scatter3d` / `pvdata_render_animation`",
              "- `npy3d_inspect` / `pvdata_inspect` 可先核对数据布局与数组范围"]

    if embed_in_paper:
        lines += ["", "### 导出到论文（用户可选）", "",
                  "在渲染引擎里点「导出到论文」，填 caption/label 后即可得到论文级 PNG 与"
                  "可直接粘贴的 LaTeX `figure` 片段；产物落在 `<产物根>/figures/`。",
                  "由用户决定是否启用，不启用则不产生任何论文产物。"]
    return "\n".join(lines)


HANDLERS = {
    "npy3d_inspect": npy3d_inspect,
    "npy3d_render_surface": npy3d_render_surface,
    "npy3d_render_animation": npy3d_render_animation,
    "pvdata_inspect": pvdata_inspect,
    "pvdata_render_scatter3d": pvdata_render_scatter3d,
    "pvdata_render_animation": pvdata_render_animation,
    "pvdata_import": pvdata_import,
    "npy3d_web_viewer": npy3d_web_viewer,
}


def get_handler(name: str):
    return HANDLERS.get(name)
