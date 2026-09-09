# -*- coding: utf-8 -*-
"""生成与 CFD_TEST 同构的演示数据集 sample_data/（合成圆柱绕流，非真实 CFD）。

结构约定（与真实 NACA_Cylinder_*.npy 完全一致）：
  NACA_Cylinder_X.npy  (T, H, W)  float64  空间 X 坐标（沿 T 不变）
  NACA_Cylinder_Y.npy  (T, H, W)  float64  空间 Y 坐标（沿 T 不变）
  NACA_Cylinder_Q.npy  (T, C, H, W) float64  C=5 个物理量通道随时间演化
用法: python make_sample.py  ->  生成 cfd_npy3d_mcp/sample_data/
"""
import os
import numpy as np

T = 48        # 时间帧
C = 5         # 通道数（与真实数据一致）
W = 201       # 列：流向 x
H = 81        # 行：横向 y


def _gen_grid():
    x = np.linspace(-4.0, 4.0, W)       # 流向
    y = np.linspace(-2.0, 2.0, H)       # 横向
    return np.meshgrid(x, y, indexing="xy")   # (H, W)


def _vortex(u, v, x, y, xc, yc, gam, sig):
    dx = x - xc
    dy = y - yc
    r2 = dx * dx + dy * dy
    f = gam / (2 * np.pi) * np.exp(-r2 / (2 * sig * sig))
    # 高斯涡核诱导速度 (切向)
    u += f * (-dy) / (r2 + 1e-12)
    v += f * (dx) / (r2 + 1e-12)
    return u, v


def gen_sample():
    """返回 dict(x=X3, y=Y3, q=Q) —— 与 npy 文件同构的数组。"""
    X2, Y2 = _gen_grid()
    x = X2[0, :]                      # 流向坐标向量
    y = Y2[:, 0]                      # 横向坐标向量
    # 圆柱几何（平滑内部遮蔽，不用 NaN 以保证动画/曲面都稳定可画）
    r = np.sqrt((X2 - 0.0) ** 2 + (Y2 - 0.0) ** 2)
    Rc = 0.5
    inside = np.clip((Rc - r) / 0.08, 0.0, 1.0)   # 0=圆柱内, 1=外

    U = np.zeros((T, C, H, W))
    X3 = np.empty((T, H, W), dtype=np.float64)
    Y3 = np.empty((T, H, W), dtype=np.float64)
    for t in range(T):
        # 背景来流 + 卡门涡街（向下游漂移、上下两列交替旋转）
        u = np.full((H, W), 1.0)
        v = np.zeros((H, W))
        s = 0.6 * t / T * 2.0                      # 涡列向下游漂移量
        sig = 0.30
        n = 8
        for k in range(n):
            xc = 1.5 + k * 1.2 + s
            gam = (-1) ** k * 0.9
            u, v = _vortex(u, v, X2, Y2, xc, 0.55, gam, sig)
            u, v = _vortex(u, v, X2, Y2, xc, -0.55, -gam, sig)
        # 圆柱绕流：圆柱附近抑制横向速度、返回流
        u *= inside
        v *= inside
        # 通道合成（与真实数据“都接近 1、个别通道带负号”同特征）
        w = (v > 0.02).astype(float) - (v < -0.02).astype(float)   # 涡街符号带
        U[t, 0] = 1.0 + 0.10 * w * np.exp(-(r - 1.0) ** 2 / 0.8)    # rho
        U[t, 1] = u                                                 # u
        U[t, 2] = v * 1.5                                           # v(带负号)
        U[t, 3] = 1.0 - 0.30 * np.exp(-r * r / (2 * Rc * Rc)) + 0.05 * w  # p(圆柱低压)
        U[t, 4] = 1.0 + 0.15 * np.exp(-(r - 1.6) ** 2 / 1.2) * (0.5 + 0.5 * np.cos(2 * np.pi * t / T))  # T
        U[t, 0] = U[t, 0] * (0.7 + 0.6 * inside)
        X3[t] = X2
        Y3[t] = Y2
    return dict(x=X3, y=Y3, q=U)


def _plane2d_vtk(out_dir=None):
    """生成一个 ASCII legacy .vtk 2D 平面场（x-y，单 z 层），供 pvdata_import 自测/演示。

    - vtkImageData（结构化点），DIMENSIONS 41x21x1，z span=0 → 满足 2D 平面判定
    - 点数组 pressure：流向余弦条纹，物理含义接近真实流场
    """
    import textwrap
    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_data")
    os.makedirs(out_dir, exist_ok=True)
    nx, ny = 41, 21
    x0, y0, dx, dy = -2.0, -1.0, 4.0 / (nx - 1), 2.0 / (ny - 1)
    rows = []
    for j in range(ny):
        y = y0 + j * dy
        vals = []
        for i in range(nx):
            x = x0 + i * dx
            r = (x * x + y * y) ** 0.5
            inside = 1.0 if r < 0.5 else 0.0          # 圆柱遮挡示意
            vals.append("%.4f" % (1.0 + 0.2 * (1 - inside)
                                  * (x + 2.0) / 4.0 * (0.5 + 0.5 * (y + 1.0))))
        rows.append(" ".join(vals))
    body = "\n".join(rows)
    content = textwrap.dedent("""\
        # vtk DataFile Version 3.0
        2D planar demo field (x-y, single z layer)
        ASCII
        DATASET STRUCTURED_POINTS
        DIMENSIONS %d %d 1
        ORIGIN %.3f %.3f 0
        SPACING %.6f %.6f 1.0
        POINT_DATA %d
        SCALARS pressure float 1
        LOOKUP_TABLE default
        %s
        """) % (nx, ny, x0, y0, dx, dy, nx * ny, body)
    p = os.path.join(out_dir, "plane2d.vtk")
    with open(p, "w", encoding="ascii") as f:
        f.write(content)
    return p


def generate(out_dir=None):
    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_data")
    os.makedirs(out_dir, exist_ok=True)
    d = gen_sample()
    paths = {
        "X": os.path.join(out_dir, "NACA_Cylinder_X.npy"),
        "Y": os.path.join(out_dir, "NACA_Cylinder_Y.npy"),
        "Q": os.path.join(out_dir, "NACA_Cylinder_Q.npy"),
    }
    for key, p in paths.items():
        np.save(p, d[key.lower()])
    pv = _plane2d_vtk(out_dir)
    print("sample_data generated:")
    for p in list(paths.values()) + [pv]:
        print("  ", p, "%.2f MB" % (os.path.getsize(p) / 1e6))
    return paths


if __name__ == "__main__":
    generate()
