# -*- coding: utf-8 -*-
"""run_format_read_check.py —— 常见数据格式读取能力检查驱动。

流程（一次 pvpython 调用完成样例生成与真实读取验证）：
1. 定位 pvpython（pvbridge.find_pvpython）；
2. pvpython make_samples_pv.py <out_dir>
   —— 现场生成 .vti/.vtu/.vtp/.vts/.vtr/.vtk/.vtm/.stl/.ply/.obj/.csv/.pvd/
      .ex2/.e/.xdmf 等 tiny 样例，并在同一进程内逐格式调用
      pvjob_pvdata.run_inspect()（扩展 pvdata_inspect 的真实读取实现），
      结果写回 out_dir/samples.json；
3. 读取 samples.json，按"能否读出数据/数组"输出支持矩阵。

运行：cd cfd-npy3d 后
    python -m checks.data_format_read.run_format_read_check [out_dir]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

_PKG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _PKG)
sys.path.insert(0, os.path.dirname(_PKG))

import pvbridge                                            # noqa: E402


def _norm_reader(name):
    s = (name or "").lower().strip("_")
    for pre in ("vtkxml", "vtk", "xml", "legacy", "exodusii", "pvd",
                "csv", "stl", "ply", "xdmf", "exo", "wavefront"):
        if s.startswith(pre):
            s = s[len(pre):]
            break
    for suf in ("filereader", "filewriter", "reader", "writer"):
        if s.endswith(suf):
            s = s[: -len(suf)]
            break
    return s.replace("_", "").strip()


def _decide(entry):
    ext = entry.get("ext", "")
    kind = entry.get("kind", "geometry")
    status = entry.get("status")
    if status == "skip":
        return "SKIP", entry.get("note", "no sample")
    err = entry.get("error")
    if status == "error" or err:
        if not entry.get("reader_known", True):
            want = entry.get("expect_reader", "")
            return ("FAIL", "README 映射的 reader '%s' 在本机 paraview.simple 不存在"
                    % want)
        return "FAIL", (err or "")[:160]
    if status != "ok":
        return "FAIL", "unexpected status %r" % status
    reader = entry.get("reader", "")
    expect = entry.get("expect_reader", "")
    if expect and _norm_reader(reader) != _norm_reader(expect):
        return "FAIL", "reader %r != 期望 %r" % (reader, expect)
    points = entry.get("points") or 0
    cells = entry.get("cells") or 0
    pa = entry.get("n_point_arrays") or 0
    ca = entry.get("n_cell_arrays") or 0
    ts = entry.get("timesteps") or []
    if kind == "table":
        return "PASS", "reader ok (表格无 points 属正常)"
    if kind == "collection":
        return ("PASS", "ok, ts=%s" % len(ts)) if ts else ("FAIL", "时间序列未读出")
    if kind == "composite":
        return "PASS", "reader ok (多块顶层无汇总 points 属正常)"
    if points > 0 or cells > 0 or pa > 0 or ca > 0:
        return "PASS", "ok"
    return "WARN", "reader 打开但顶层 points/cells/arrays 全 0"


def _readable_summary(entry):
    d = entry
    pa = d.get("point_arrays") or []
    ca = d.get("cell_arrays") or []
    names = ",".join(pa[:4])
    if len(pa) > 4:
        names += ",..."
    ca_s = ",".join(ca[:3])
    return ("pts=%s cells=%s arrays[%d/%d]=%s%s ts=%s" % (
        d.get("points"), d.get("cells"),
        d.get("n_point_arrays") or 0, d.get("n_cell_arrays") or 0,
        names, (";c=" + ca_s) if ca_s else "",
        ",".join(str(round(float(t), 3)) for t in (d.get("timesteps") or []))))


def run(out_dir=None):
    lines = []
    pv = pvbridge.find_pvpython()
    if not pv:
        return (False, ["pvpython not available; cannot verify data formats"])
    if not out_dir:
        out_dir = os.path.join(pvbridge.RUN_DIR, "data_format_read")
    os.makedirs(out_dir, exist_ok=True)
    gen = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "make_samples_pv.py")
    proc = subprocess.run([pv, gen, out_dir], capture_output=True,
                          text=True, timeout=900)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout or "").splitlines()[-30:])
        return (False, ["sample generator failed (exit %d)" % proc.returncode,
                        tail])
    with open(os.path.join(out_dir, "samples.json"), "r", encoding="utf-8") as f:
        data = json.load(f)
    entries = data.get("samples", [])
    if not entries:
        return (False, ["no samples produced"])
    hdr = "| 格式 | 类别 | 状态 | 证据 |"
    sep = "|---|---|---|---|"
    rows = [hdr, sep]
    for e in entries:
        st, why = _decide(e)
        ev = _readable_summary(e) if e.get("status") == "ok" else \
            (e.get("note") or "")
        rows.append("| %s | %s | **%s** | %s |" % (
            e.get("ext", ""), e.get("kind", ""), st, ev))
        rows.append("|   |   | 原因 | %s |" % why)
    n_pass = sum(1 for e in entries if _decide(e)[0] == "PASS")
    n_warn = sum(1 for e in entries if _decide(e)[0] == "WARN")
    n_fail = sum(1 for e in entries if _decide(e)[0] == "FAIL")
    n_skip = sum(1 for e in entries if _decide(e)[0] == "SKIP")
    total = len(entries)
    ok = n_fail == 0 and total > 0
    rows.append("")
    rows.append("汇总: 共 %d 格式 | PASS %d | WARN %d | FAIL %d | SKIP %d"
                % (total, n_pass, n_warn, n_fail, n_skip))
    rows.append("样例与详细结果目录: %s" % out_dir)
    if n_warn:
        rows.append("WARN 说明: reader 能打开文件，但顶层信息可能因多块/表格结构"
                    "不直接暴露 points/arrays，请结合样例结果进一步确认。")
    lines += rows
    return (ok, lines)


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else None
    ok, lines = run(out_dir)
    for ln in lines:
        print(ln)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
