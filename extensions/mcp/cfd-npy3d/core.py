# -*- coding: utf-8 -*-
"""cfd_npy3d_mcp.core —— X/Y/Q npy 数据集协议解析与 3D 可视化实现。

协议（与真实 CFD_TEST/NACA_Cylinder_*.npy 一致）:
    X/Y: (T,H,W) 或 (H,W) 的空间坐标；当为 (T,H,W) 时沿 T 应相同（只读一帧即可）。
    Q  : (H,W) | (C,H,W) | (T,H,W) | (T,C,H,W) 的物理量场，
         首轴 T=时间帧，次轴 C=物理量通道（可缺省）。
所有 .npy 在磁盘上通过 mmap 流式读取，1 GB 级大数据不必整体载入内存。
"""
from __future__ import annotations

import datetime
import os
import re
from dataclasses import dataclass
from typing import Optional

import numpy as np


def sanitize_case(name: str) -> str:
    """把自由场景名安全化成目录名（沿用主 MCP 的归档规则）。"""
    if name is None:
        return "default"
    s = str(name).strip().replace("\\", "_").replace("/", "_")
    s = re.sub(r'[<>:"|?*\x00-\x1f]', "_", s)
    s = s.strip(" ._")
    if not s or s in (".", ".."):
        s = "default"
    return s


def _unique_path(path: str) -> str:
    """同秒写入碰撞守卫：xxx.png / xxx_1.png / xxx_2.png ..."""
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    i = 1
    while os.path.exists("%s_%d%s" % (stem, i, ext)):
        i += 1
    return "%s_%d%s" % (stem, i, ext)


def _find_npy(data_dir: str, tokens: tuple) -> dict:
    """目录内按文件名 token(X/Y/Q) 找到对应 .npy；找不到则抛可读错误。"""
    if not os.path.isdir(data_dir):
        raise FileNotFoundError("数据目录不存在: %s" % data_dir)
    hits = {}
    for f in os.listdir(data_dir):
        if not f.lower().endswith(".npy"):
            continue
        base = os.path.splitext(f)[0].lower()
        parts = re.split(r"[_\-\s.]+", base)
        for token, role in tokens.items():
            if token in parts and role not in hits:
                hits[role] = os.path.join(data_dir, f)
    missing = [r for r in ("X", "Y", "Q") if r not in hits]
    if missing:
        found = __import__("glob").glob(os.path.join(data_dir, "*.npy"))
        names = [os.path.basename(f) for f in found]
        raise FileNotFoundError(
            "目录 %s 中未找到字段 %s 对应的 npy（期望文件名含 X/Y/Q 分词，如 NACA_Cylinder_X.npy）。"
            "现有 npy: %s" % (data_dir, missing, names or "（无）"))
    return hits


@dataclass
class NpyDataset:
    data_dir: str
    files: dict                 # role -> path
    X: np.ndarray               # (H,W) 一帧坐标（已拷贝）
    Y: np.ndarray
    Q_path: str
    shape: tuple                # Q 原始 shape
    dtype: np.dtype
    T: int
    C: int
    H: int
    W: int
    x_axis: int                 # 流向/列方向的网格轴（0=axis1 行,1=axis2 列）

    @property
    def npts(self) -> int:
        return self.H * self.W

    def load_q_frame(self, t: int, c: Optional[int] = None) -> np.ndarray:
        """按帧流式取 Q 的 2D 切片；c=None 且 C==1 时返回单通道。"""
        q = np.load(self.Q_path, mmap_mode="r")
        try:
            if q.ndim == 2:
                a = q
            elif q.ndim == 3 and q.shape[0] == self.T and self.C == 1:
                a = q[min(t, q.shape[0] - 1)]
            elif q.ndim == 3 and q.shape[0] == self.C and self.T == 1:
                a = q[min(c or 0, q.shape[0] - 1)]
            elif q.ndim == 4:
                ti = min(t, q.shape[0] - 1)
                if self.C > 1:
                    a = q[ti, min(c or 0, self.C - 1)]
                else:
                    a = q[ti]
            else:
                raise ValueError("无法解释的 Q 维度 %s" % (q.shape,))
        finally:
            pass  # mmap 句柄随数组 GC 释放
        return np.array(a, dtype=np.float64, copy=True)

    def frame_stats(self, t: int) -> list:
        """某帧各通道 min/max/mean/nan%。"""
        out = []
        for c in range(self.C):
            a = self.load_q_frame(t, c)
            out.append(dict(ch=c, nmin=float(np.nanmin(a)), nmax=float(np.nanmax(a)),
                            mean=float(np.nanmean(a)),
                            nanpct=100.0 * float(np.isnan(a).mean())))
        return out

    def coord_range(self) -> dict:
        x, y = self.X, self.Y
        return dict(xmin=float(np.nanmin(x)), xmax=float(np.nanmax(x)),
                    ymin=float(np.nanmin(y)), ymax=float(np.nanmax(y)))

    def inspect_md(self) -> str:
        """生成 markdown 描述（供 agent 阅读）。"""
        fs = []
        for role in ("X", "Y", "Q"):
            p = self.files[role]
            fs.append("%s=`%s` (%.1f MB)" % (role, os.path.basename(p),
                                             os.path.getsize(p) / 1e6))
        cr = self.coord_range()
        lines = [
            "## npy3d 数据集",
            "数据目录: `%s`" % self.data_dir,
            "",
            "- 文件: %s" % " ; ".join(fs),
            "- Q 原始 shape: `%s`  dtype: `%s`" % (self.shape, self.dtype),
            "- 语义推断: 时间帧 **T=%d**, 物理量通道 **C=%d**, 网格 **H×W = %d×%d** (%d 点)"
            % (self.T, self.C, self.H, self.W, self.npts),
            "- 坐标范围: x∈[%.4g, %.4g], y∈[%.4g, %.4g]" % (cr["xmin"], cr["xmax"], cr["ymin"], cr["ymax"]),
            "",
            "**第 0 帧各通道统计**",
        ]
        lines.append("| ch | min | max | mean | nan% |")
        lines.append("|---|---|---|---|---|")
        for s in self.frame_stats(0):
            lines.append("| %d | %.5g | %.5g | %.5g | %.2f |" %
                         (s["ch"], s["nmin"], s["nmax"], s["mean"], s["nanpct"]))
        lines += [
            "",
            "**示例**（用包内自带数据目录跑）:",
            "- `npy3d_render_surface(data_dir=..., frame=0, channels=\"all\")`",
            "- `npy3d_render_animation(data_dir=..., channel=0, max_frames=24)`",
        ]
        return "\n".join(lines)


def open_dataset(data_dir: str,
                 x_token: str = "x", y_token: str = "y", q_token: str = "q") -> NpyDataset:
    """打开数据目录并推断 X/Y/Q 语义（mmap 只读，不做整载）。"""
    files = _find_npy(data_dir, {x_token: "X", y_token: "Y", q_token: "Q"})
    xa = np.load(files["X"], mmap_mode="r")
    ya = np.load(files["Y"], mmap_mode="r")
    qa = np.load(files["Q"], mmap_mode="r")
    if xa.shape != ya.shape:
        raise ValueError("X/Y shape 不一致: %s vs %s" % (xa.shape, ya.shape))
    if xa.ndim == 2:
        H, W = xa.shape
        X, Y = np.array(xa, copy=True), np.array(ya, copy=True)
    elif xa.ndim == 3:
        # 坐标沿首轴重复（时间帧）——只取最后一帧即可
        X = np.array(xa[-1], copy=True)
        Y = np.array(ya[-1], copy=True)
        H, W = X.shape
    else:
        raise ValueError("不支持 X/Y 维度: %s" % (xa.shape,))

    q = qa
    T = C = 1
    if q.ndim == 4:
        if q.shape[2:] != (H, W):
            raise ValueError("Q 网格 %s 与 X/Y %dx%d 不匹配" % (q.shape[2:], H, W))
        T, C = q.shape[0], q.shape[1]
    elif q.ndim == 3:
        if q.shape[1:] != (H, W):
            raise ValueError("Q shape %s 与网格 %dx%d 不匹配" % (q.shape, H, W))
        if xa.ndim == 3:
            T, C = q.shape[0], 1      # X/Y 带时间轴 -> Q 为 (T,H,W) 单通道
        else:
            T, C = 1, q.shape[0]      # X/Y 为静态网格 -> Q 解释为 (C,H,W) 多通道单帧

    elif q.ndim == 2:
        if q.shape != (H, W):
            raise ValueError("Q shape %s 与网格 %dx%d 不匹配" % (q.shape, H, W))
        T = C = 1
    else:
        raise ValueError("不支持的 Q 维度: %s" % (q.shape,))

    return NpyDataset(data_dir=data_dir, files=files, X=X, Y=Y,
                      Q_path=files["Q"], shape=qa.shape, dtype=qa.dtype,
                      T=T, C=C, H=H, W=W, x_axis=1)


def _surface_from(ax, x, y, z):
    """带 NaN 数据的稳健 3D 曲面：基本无 NaN 用结构化 plot_surface，
    有空洞则退化为三角化表面。返回可挂 colorbar 的 mappable。"""
    m = np.ma.masked_invalid(z)
    if m.count() == 0:
        raise ValueError("该帧通道全为 NaN，无法绘图")
    if m.count() >= 0.999 * z.size:
        return ax.plot_surface(x, y, z, cmap="jet", linewidth=0,
                               antialiased=True, rstride=1, cstride=1)
    xx, yy = x[~m.mask], y[~m.mask]
    zz = z[~m.mask]
    # 三角化有空洞表面（对大数据可降低分辨率）
    stride = max(1, int(np.sqrt(z.size / 30000)))
    idx = (slice(None, None, stride), slice(None, None, stride))
    m2 = np.ma.masked_invalid(z[idx])
    if m2.count() < 30:
        raise ValueError("有效点过少无法做三维曲面")
    import matplotlib.tri as mtri
    tri = mtri.Triangulation(x[idx][~m2.mask], y[idx][~m2.mask])
    return ax.plot_trisurf(tri, z[idx][~m2.mask], cmap="jet")


def render_surface(ds: NpyDataset, frame: int = 0, channels="0",
                   case: str | None = None, out_root: str = "output",
                   azim: int = -60, elev: int = 35,
                   dpi: int = 150, show_2d: bool = True) -> dict:
    """单帧三维曲面图：z 与颜色均为 Q（可多通道并排），存 PNG。

    返回 dict(path=..., md=...)。
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # 通道选择解析
    chs = _parse_channels(channels, ds.C)
    if frame < 0 or frame >= ds.T:
        raise ValueError("frame=%d 超出范围 [0, %d)" % (frame, ds.T))

    x, y = ds.X, ds.Y
    n = len(chs)
    ncols = n if not show_2d else n + (1 if n == 1 else 0)
    nrows = 1 if ncols <= 3 else (2 if ncols <= 6 else 3)
    ncols = int(np.ceil(ncols / nrows))
    fig = plt.figure(figsize=(5.4 * ncols, 4.6 * nrows))
    spec = fig.add_gridspec(nrows, ncols)
    axes = []
    stats = []
    for k, ch in enumerate(chs):
        z = ds.load_q_frame(frame, ch)
        stats.append(dict(ch=ch, nmin=float(np.nanmin(z)), nmax=float(np.nanmax(z)),
                          mean=float(np.nanmean(z)), nanpct=float(np.isnan(z).mean()) * 100))
        ax = fig.add_subplot(spec[k // ncols, k % ncols], projection="3d")
        surf = _surface_from(ax, x, y, z)
        ax.set_title("Q ch%d (f=%d)  [%.3g, %.3g]" % (ch, frame, stats[-1]["nmin"], stats[-1]["nmax"]),
                     fontsize=10)
        ax.set_xlabel("X"); ax.set_ylabel("Y"); ax.set_zlabel("Q")
        ax.view_init(elev=elev, azim=azim)
        ax.tick_params(labelsize=8)
        cb = fig.colorbar(surf, ax=ax, shrink=0.62, pad=0.06)
        cb.ax.tick_params(labelsize=7)
        axes.append(ax)
    if show_2d and n == 1:
        # 附加 2D 俯视对照（点云着色，天然支持非结构化/贴体网格）
        ax2 = fig.add_subplot(spec[0, -1])
        z = ds.load_q_frame(frame, chs[0])
        m = np.isfinite(z)
        sc = ax2.scatter(x[m], y[m], c=z[m], s=0.6, cmap="jet", rasterized=True)
        ax2.set_title("2D top view (validation)", fontsize=10)
        ax2.set_xlabel("X"); ax2.set_ylabel("Y")
        fig.colorbar(sc, ax=ax2, shrink=0.8)
    fig.suptitle("CFD npy 3D surface: frame=%d  channels=%s" % (frame, chs), y=0.99)
    fig.tight_layout()

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    sub = os.path.join(out_root, "cases", sanitize_case(case), "render") if case else \
          os.path.join(out_root, "render")
    os.makedirs(sub, exist_ok=True)
    path = _unique_path(os.path.join(sub, "npy3d_surface_f%d_%s.png" % (frame, ts)))
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return dict(path=path, md="已生成三维曲面图: `%s`\n%s" % (path, _stats_md(stats)))


def _parse_channels(channels, C):
    if channels is None or str(channels).strip().lower() in ("all", ""):
        return list(range(C))
    out = []
    for tok in str(channels).replace(" ", "").split(","):
        if not tok:
            continue
        if "-" in tok and tok.count("-") == 1:
            a, b = tok.split("-")
            out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(tok))
    out = [c for c in dict.fromkeys(out) if 0 <= c < C]
    if not out:
        raise ValueError("channels=%s 解析后为空或越界（C=%d）" % (channels, C))
    return out


def _stats_md(stats) -> str:
    rows = ["| ch | min | max | mean | nan% |", "|---|---|---|---|---|"]
    for s in stats:
        rows.append("| %d | %.5g | %.5g | %.5g | %.2f |" %
                    (s["ch"], s["nmin"], s["nmax"], s["mean"], s["nanpct"]))
    return "\n".join(rows)


def render_animation(ds: NpyDataset, channel: int = 0, case: str | None = None,
                     out_root: str = "output", max_frames: int = 48,
                     fps: int = 6, azim: int = -60, elev: int = 35,
                     dpi: int = 90) -> dict:
    """单通道时间演化 GIF：每帧重建 3D 曲面，颜色范围固定在抽样帧全局区间。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation

    if ds.T < 2:
        raise ValueError("仅 1 帧，无法做时间动画")
    if not (0 <= channel < ds.C):
        raise ValueError("channel=%d 越界（C=%d）" % (channel, ds.C))
    idx = np.unique(np.linspace(0, ds.T - 1, min(max_frames, ds.T)).astype(int))
    # 预扫：抽样帧必须无 NaN（有 NaN 的通道动画不可靠，给出明确报错）
    bad = []
    for t in idx:
        if np.isnan(ds.load_q_frame(int(t), channel)).any():
            bad.append(int(t))
    if bad:
        raise ValueError("channel=%d 在抽样帧 %s 含 NaN，无法生成稳定动画；"
                         "可换无 NaN 的帧段/通道。" % (channel, bad[:8]))
    lo, hi = np.inf, -np.inf
    for t in idx:
        a = ds.load_q_frame(int(t), channel)
        lo, hi = min(lo, float(np.nanmin(a))), max(hi, float(np.nanmax(a)))

    x, y = ds.X, ds.Y
    fig = plt.figure(figsize=(7.6, 6.2))
    ax = fig.add_subplot(111, projection="3d")
    norm = plt.Normalize(lo, hi)
    ax.set_xlabel("X"); ax.set_ylabel("Y"); ax.set_zlabel("Q")
    ax.view_init(elev=elev, azim=azim)
    ax.set_title("Q ch%d @ frame 0/%d" % (channel, ds.T - 1))
    mapp = plt.cm.ScalarMappable(norm=norm, cmap="jet")
    mapp.set_array([])
    fig.colorbar(mapp, ax=ax, shrink=0.7)

    surf = [None]

    def update(ti):
        z = ds.load_q_frame(int(ti), channel)
        if surf[0] is not None:
            surf[0].remove()
        ax.set_title("Q ch%d @ frame %d/%d" % (channel, int(ti), ds.T - 1))
        surf[0] = ax.plot_surface(x, y, z, cmap="jet", norm=norm, linewidth=0,
                                  antialiased=True, rstride=1, cstride=1)
        return (surf[0],)

    anim = FuncAnimation(fig, update, frames=idx.tolist(), blit=False, repeat=False)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    sub = os.path.join(out_root, "cases", sanitize_case(case), "render") if case else \
          os.path.join(out_root, "render")
    os.makedirs(sub, exist_ok=True)
    path = _unique_path(os.path.join(sub, "npy3d_anim_ch%d_%s.gif" % (channel, ts)))
    anim.save(path, writer="pillow", fps=fps, dpi=dpi)
    plt.close(fig)
    return dict(path=path,
                md="已生成三维时间动画: `%s`\n（channel=%d, 帧 %d 张, 数值范围 [%.4g, %.4g]）"
                   % (path, channel, len(idx), lo, hi))


def load_npz_points(npz_path: str):
    """读 pvjob 导出的 npz，返回 (pts:(N,3) float64, val:(N,) float64)。"""
    d = np.load(npz_path)
    return np.asarray(d["pts"], dtype=np.float64), np.asarray(d["val"], dtype=np.float64)


def _scatter_sizes(n: int) -> float:
    """点数多则点更小，保证既不太疏也不糊成一片。"""
    return float(np.clip(4.0 * np.sqrt(8000.0 / max(n, 1)), 0.25, 4.0))


def _box_aspect(pts) -> tuple:
    lo = pts.min(axis=0)
    hi = pts.max(axis=0)
    span = np.maximum(hi - lo, 1e-9)
    m = span.min()
    return tuple(float(s / m) for s in span)


def _point_ax(fig, ax, pts, val, norm, cmap, azim, elev, title):
    s = _scatter_sizes(len(pts))
    sc = ax.scatter(pts[:, 0], pts[:, 1], pts[:, 2], c=val, cmap=cmap,
                    norm=norm, s=s, linewidths=0, depthshade=False)
    ax.view_init(elev=elev, azim=azim)
    ax.set_xlabel("X"); ax.set_ylabel("Y"); ax.set_zlabel("Z")
    ax.set_title(title, fontsize=11)
    try:
        ax.set_box_aspect(_box_aspect(pts))
    except Exception:                                  # noqa: BLE001
        pass
    return sc


def render_point_cloud(pts, val, array_name, out_root, case=None, azim=-55,
                       elev=25, cmap="coolwarm", tag="pvdata_scatter",
                       dpi=140, time_label=None, npts_orig=None):
    """三维点云着色图（ParaView 数据点 + 标量颜色），存 PNG，返回 dict(path, md)。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if len(pts) == 0:
        raise ValueError("点云为空，无法绘图")
    if np.isfinite(val).sum() == 0:
        raise ValueError("标量全为非有限值，无法绘图")
    vmin, vmax = float(np.nanmin(val)), float(np.nanmax(val))
    fig = plt.figure(figsize=(10.5, 8.0))
    ax = fig.add_subplot(111, projection="3d")
    norm = plt.Normalize(vmin, vmax)
    sc = _point_ax(fig, ax, pts, val, norm, cmap, azim, elev,
                   "3D points: %s  [%.4g, %.4g]" % (array_name, vmin, vmax))
    cb = fig.colorbar(sc, ax=ax, shrink=0.75, pad=0.08)
    cb.set_label(array_name)
    sub = ("points %d" % len(pts) if not npts_orig else "points %d/%d (sampled)"
           % (len(pts), npts_orig))
    fig.suptitle("ParaView dataset point cloud\n%s | %s%s" %
                 (array_name, sub, (" | t=%s" % time_label) if time_label else ""),
                 y=1.02, fontsize=11)
    fig.tight_layout()

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(out_root, "cases", sanitize_case(case), "render") if case else \
        os.path.join(out_root, "render")
    os.makedirs(out_dir, exist_ok=True)
    path = _unique_path(os.path.join(out_dir, "%s_%s.png" % (tag, ts)))
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return dict(path=path, vmin=vmin, vmax=vmax,
                md="已生成三维点云图: `%s`\n- array=`%s`  range=[%.5g, %.5g]  "
                   "点数=%d%s" % (path, array_name, vmin, vmax, len(pts),
                                  ("(原 %d 点)" % npts_orig) if npts_orig else ""))


def render_point_cloud_animation(frames, array_name, out_root, case=None,
                                 azim=-55, elev=25, cmap="coolwarm", fps=6,
                                 dpi=100, tag="pvdata_anim", time_labels=None):
    """多时间步点云动画：frames = [(pts, val), ...]，固定颜色区间，存 GIF。

    time_labels 长度与 frames 相同则写入每帧标题。返回 dict(path, md)。
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation

    if not frames:
        raise ValueError("无动画帧")
    vmin = min(float(np.nanmin(v)) for _, v in frames)
    vmax = max(float(np.nanmax(v)) for _, v in frames)
    fig = plt.figure(figsize=(9.6, 8.0))
    ax = fig.add_subplot(111, projection="3d")
    norm = plt.Normalize(vmin, vmax)
    sc = _point_ax(fig, ax, frames[0][0], frames[0][1], norm, cmap, azim, elev,
                   "frame 0/%d" % (len(frames) - 1))
    cb = fig.colorbar(sc, ax=ax, shrink=0.75, pad=0.08)
    cb.set_label(array_name)
    fig.suptitle("%s | frames=%d  range=[%.4g, %.4g]" %
                 (array_name, len(frames), vmin, vmax), y=1.02)

    artists = [sc]

    def update(i):
        nonlocal artists
        for a in artists:
            try:
                a.remove()
            except Exception:                          # noqa: BLE001
                pass
        pts, val = frames[i]
        sc2 = _point_ax(fig, ax, pts, val, norm, cmap, azim, elev,
                        "t=%s" % (time_labels[i] if time_labels and i < len(time_labels)
                                  else "frame %d/%d" % (i, len(frames) - 1)))
        artists = [sc2]
        return (sc2,)

    anim = FuncAnimation(fig, update, frames=len(frames), blit=False, repeat=False)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(out_root, "cases", sanitize_case(case), "render") if case else \
        os.path.join(out_root, "render")
    os.makedirs(out_dir, exist_ok=True)
    path = _unique_path(os.path.join(out_dir, "%s_%s.gif" % (tag, ts)))
    anim.save(path, writer="pillow", fps=fps, dpi=dpi)
    plt.close(fig)
    return dict(path=path, md="已生成三维点云动画: `%s`\n- array=`%s`  帧数=%d  "
                              "固定颜色范围=[%.5g, %.5g]" %
               (path, array_name, len(frames), vmin, vmax))


SAMPLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_data")
