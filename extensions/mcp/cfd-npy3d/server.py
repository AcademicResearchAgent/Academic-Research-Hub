# -*- coding: utf-8 -*-
"""cfd-npy-3d MCP server —— 把 CFD 数据变成可用的三维可视化 MCP 工具。

两类数据源（与 1.1.0 行为完全一致）：
  - numpy 场 (X/Y/Q .npy)：曲面图 / 时间 GIF 动画 / 检视（npy3d_*）；
  - ParaView 支持的常见文件格式 (.vtu/.vtp/.vti/.vts/.vtr/.vtk/.vtm/.ex2/
    .pvd/.xdmf/.stl/.ply/.obj/.csv ...)：检视、三维点云着色图、逐时间步
    点云动画（pvdata_*）。ParaView 格式通过 pvpython 任务桥读取。

架构（v1.2 起契约驱动，参考 academic-research-skills 的组织纪律）：
  manifest.json + tools/*.json  = 工具注册契约（数据驱动）
  registry.py                   = 契约加载/校验
  handlers.py                   = 工具的实现（显式签名）
  server.py                     = 启动时按 registry 自动注册工具（仅此职责）
  checks/                       = 契约<->实现<->技能文档 一致性质量门
  skills/*/SKILL.md             = 技能描述层（可选：按 skill 方式注册二选一）

入口/环境变量/产物归档不变：无 --selftest/--check 时以 stdio 协议运行；
环境变量 NPY3D_OUT_ROOT（产物根）、PARAVIEW_PVPYTHON（pvpython 路径）。
"""
from __future__ import annotations

import os
import sys

import matplotlib
matplotlib.use("Agg")

from mcp.server.fastmcp import FastMCP

import core
import handlers
import registry


def _build_mcp() -> FastMCP:
    """按 manifest/tools/*.json 契约自动注册工具。

    新增工具：tools/<name>.json + manifest 登记 + handlers.HANDLERS 实现，
    无需改本函数；契约与签名不一致由 checks/ 质量门拦截。
    """
    mcp = FastMCP("cfd-npy-3d")
    errs = registry.validate_registry()
    if errs:
        raise RuntimeError("工具注册表非法（manifest/tools/*.json）：\n  "
                           + "\n  ".join(errs))
    specs = registry.tool_specs()
    for spec in specs:
        fn = handlers.get_handler(spec["name"])
        if fn is None:
            raise RuntimeError("manifest 声明 %s 但 handlers 未实现"
                               % spec["name"])
        mcp.add_tool(fn,
                     name=spec["name"],
                     title=spec.get("title"),
                     description=spec.get("description", ""))
    return mcp


mcp = _build_mcp()
OUT_ROOT = registry.OUT_ROOT


def _selftest() -> int:
    import glob
    from checks import check_registry_consistency
    try:
        # 0) 契约/实现/技能文档 一致性质量门
        ok, lines = check_registry_consistency.run()
        for ln in lines:
            print("check |", ln)
        assert ok, "registry consistency check failed"
        print("check ok")

        # 6) 注册清单核对：按 manifest 实际注册数与名称
        specs = registry.tool_specs()
        print("registry tools=%d: %s"
              % (len(specs), ", ".join(s["name"] for s in specs)))
        assert len(specs) == len(handlers.HANDLERS)

        # 1) 演示数据兜底生成
        sample = os.path.join(registry.BASE, "sample_data")
        if not glob.glob(os.path.join(sample, "*.npy")):
            import make_sample
            make_sample.generate(sample)
        ds = core.open_dataset(sample)
        print("inspect ... T=%d C=%d HxW=%dx%d" % (ds.T, ds.C, ds.H, ds.W))
        assert ds.T >= 2 and ds.C == 5

        # 2) 曲面（单通道 + 多通道）
        r1 = handlers.npy3d_render_surface(frame=0, channels="0",
                                           case="cfd_npy3d_selftest")
        assert os.path.isfile(r1.split("`")[1]), r1[:120]
        assert os.path.getsize(r1.split("`")[1]) > 20_000
        r2 = handlers.npy3d_render_surface(frame=3, channels="all",
                                           case="cfd_npy3d_selftest")
        assert os.path.isfile(r2.split("`")[1]), r2[:120]
        print("surface ok ->", os.path.basename(r1.split("`")[1]))
        print("surface(all) ok ->", os.path.basename(r2.split("`")[1]))

        # 3) 动画 GIF
        r3 = handlers.npy3d_render_animation(channel=0, case="cfd_npy3d_selftest",
                                             max_frames=24, fps=6)
        assert os.path.isfile(r3.split("`")[1]), r3[:120]
        print("animation ok ->", os.path.basename(r3.split("`")[1]))

        # 4) 真实数据兼容性（若存在）
        real = os.path.join(registry.WORKSPACE, "CFD_TEST")
        if os.path.isdir(real) and glob.glob(os.path.join(real, "*.npy")):
            dr = core.open_dataset(real)
            print("real CFD_TEST ok: T=%d C=%d HxW=%dx%d" % (dr.T, dr.C, dr.H, dr.W))
            rr = handlers.npy3d_render_surface(
                data_dir=real, frame=0, channels="0", case="cfd_npy3d_selftest")
            assert os.path.isfile(rr.split("`")[1]), rr[:120]
            print("real surface ok ->", os.path.basename(rr.split("`")[1]))

        # 5) ParaView 格式（pvpython 可用时，用自带 ex2 示例）
        import pvbridge
        if pvbridge.available():
            cands = []
            try:
                ex = os.path.join(os.path.dirname(os.path.dirname(
                    pvbridge.find_pvpython())), "examples", "disk_out_ref.ex2")
                cands.append(ex)
            except Exception:                          # noqa: BLE001
                pass
            cands += [r"D:\Program Files\ParaView 6.0.1\examples\disk_out_ref.ex2"]
            ex2 = next((c for c in cands if os.path.isfile(c)), None)
            if ex2:
                meta = pvbridge.run_job("inspect", {"file_path": ex2})
                print("pvdata inspect ok: steps=%d pts=%s arrays=%d"
                      % (len(meta.get("timesteps") or []), meta.get("points"),
                         len(meta.get("point_arrays", []))))
                r4 = handlers.pvdata_render_scatter3d(
                    file_path=ex2, array_name="Temp", timestep_index=0,
                    max_points=80000, case="cfd_npy3d_selftest")
                assert os.path.isfile(r4.split("`")[1]), r4[:120]
                print("pvdata scatter3d ok")
                r5 = handlers.pvdata_render_animation(
                    file_path=ex2, array_name="Temp", max_frames=6,
                    max_points=50000, fps=4, case="cfd_npy3d_selftest")
                assert os.path.isfile(r5.split("`")[1]), r5[:120]
                print("pvdata animation ok")
            else:
                print("skip pvdata: no ex2 example found near pvpython")

            # 5b) import2d E2E：2D 平面样本 -> X/Y/Q .npy -> npy3d 曲面消费
            import make_sample
            plane = make_sample._plane2d_vtk(sample)
            if os.path.isfile(plane):
                out_msg = handlers.pvdata_import(
                    file_path=plane, array_name="pressure", time_slice="0",
                    sample_w=0, sample_h=0, case="cfd_npy3d_selftest")
                data_dir = None
                if "data_dir): `" in out_msg:
                    data_dir = out_msg.split("data_dir): `", 1)[1].split("`", 1)[0]
                assert data_dir and os.path.isdir(data_dir), out_msg[:300]
                for nf in ("X.npy", "Y.npy", "Q.npy"):
                    assert os.path.isfile(os.path.join(data_dir, nf)), nf
                print("pvdata import2d ok ->", os.path.basename(data_dir))
                r6 = handlers.npy3d_render_surface(
                    data_dir=data_dir, channels="0", frame=0,
                    case="cfd_npy3d_selftest")
                assert os.path.isfile(r6.split("`")[1]), r6[:120]
                print("import2d -> render_surface ok")
            else:
                print("skip pvdata import2d: plane2d.vtk missing")
        else:
            print("skip pvdata: pvpython not available")
        print("ALL SELFTEST STEPS OK")
        print("outputs under:", OUT_ROOT)
        return 0
    except Exception as e:                            # noqa: BLE001
        print("SELFTEST FAILED:")
        print(str(e))
        return 1


def _check() -> int:
    """独立跑一致性质量门（等价于 python checks/check_registry_consistency.py）。"""
    from checks import check_registry_consistency
    ok, lines = check_registry_consistency.run()
    for ln in lines:
        print(ln)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return _selftest()
    if "--check" in sys.argv:
        return _check()
    mcp.run()                                          # stdio transport
    return 0


if __name__ == "__main__":
    sys.exit(main())
