# -*- coding: utf-8 -*-
"""make_samples_pv.py —— 在 pvpython 下现场生成常见数据格式 tiny 样例。

用法: pvpython make_samples_pv.py <out_dir>

在 <out_dir> 写出一组极小样例文件与 samples.json 清单，供
run_format_read_check.py 逐格式做读取验证（走 pvjob_pvdata 真实读取路径）。
"""
import json
import os
import shutil
import sys

import numpy as np

from paraview import simple as pvs

try:
    import vtkmodules.all as vtk
except Exception:                                   # noqa: BLE001
    import vtk
from vtkmodules.util.numpy_support import numpy_to_vtk

_PKG = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, _PKG)
try:
    from pvjob_pvdata import READERS
except Exception:                                   # noqa: BLE001
    READERS = {}


def _scalar(name, values):
    a = numpy_to_vtk(np.asarray(values, dtype=np.float64))
    a.SetName(name)
    return a


def _image():
    ds = vtk.vtkImageData()
    ds.SetDimensions(3, 4, 1)
    ds.SetOrigin(0.0, 0.0, 0.0)
    ds.SetSpacing(0.5, 0.5, 0.5)
    ds.GetPointData().AddArray(_scalar(
        "T", np.arange(12, dtype=np.float64)))
    return ds


def _points3(coords):
    pts = vtk.vtkPoints()
    n = len(coords) // 3
    pts.SetNumberOfPoints(n)
    for i in range(n):
        pts.SetPoint(i, coords[3 * i], coords[3 * i + 1], coords[3 * i + 2])
    return pts


def _ugrid():
    pts = _points3([
        0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0,
        0, 0, 1, 1, 0, 1, 1, 1, 1, 0, 1, 1])
    ds = vtk.vtkUnstructuredGrid()
    ds.SetPoints(pts)
    hexa = vtk.vtkHexahedron()
    for i in range(8):
        hexa.GetPointIds().SetId(i, i)
    ds.InsertNextCell(hexa.GetCellType(), hexa.GetPointIds())
    ds.GetPointData().AddArray(_scalar("u", np.arange(8, dtype=np.float64)))
    return ds


def _tri():
    pts = _points3([0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0])
    ds = vtk.vtkPolyData()
    ds.SetPoints(pts)
    ds.GetPointData().AddArray(_scalar("s", np.arange(4, dtype=np.float64)))
    cells = vtk.vtkCellArray()
    ids = vtk.vtkIdList()
    ids.InsertNextId(0)
    ids.InsertNextId(1)
    ids.InsertNextId(2)
    cells.InsertNextCell(ids)
    ids2 = vtk.vtkIdList()
    ids2.InsertNextId(0)
    ids2.InsertNextId(2)
    ids2.InsertNextId(3)
    cells.InsertNextCell(ids2)
    ds.SetPolys(cells)
    return ds


def _struct():
    ds = vtk.vtkStructuredGrid()
    ds.SetDimensions(3, 4, 1)
    coords = []
    for j in range(4):
        for i in range(3):
            coords += [i * 0.5, j * 0.5, 0.0]
    ds.SetPoints(_points3(coords))
    ds.GetPointData().AddArray(_scalar("v", np.arange(12, dtype=np.float64)))
    return ds


def _rect():
    ds = vtk.vtkRectilinearGrid()
    ds.SetDimensions(3, 4, 1)
    ds.SetXCoordinates(_scalar("_x", [0.0, 0.5, 1.0]))
    ds.SetYCoordinates(_scalar("_y", [0.0, 0.3, 0.6, 0.9]))
    ds.SetZCoordinates(_scalar("_z", [0.0]))
    ds.GetPointData().AddArray(_scalar("p", np.arange(12, dtype=np.float64)))
    return ds


def _multiblock():
    mb = vtk.vtkMultiBlockDataSet()
    mb.SetNumberOfBlocks(2)
    mb.SetBlock(0, _image())
    mb.SetBlock(1, _tri())
    return mb


def _table():
    n = 6
    tab = vtk.vtkTable()
    for name, vals in (("x", np.linspace(0, 1, n)),
                       ("y", np.linspace(0, 2, n)),
                       ("z", np.zeros(n)),
                       ("T", np.arange(n, dtype=np.float64))):
        tab.AddColumn(_scalar(name, vals))
    return tab


def _write_xml(writer_cls, obj, path):
    w = writer_cls()
    w.SetFileName(path)
    w.SetInputData(obj)
    w.Write()


def _write_text(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _find_example(cands):
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def _add_xdmf(out_dir, samples, add):
    if not hasattr(vtk, "vtkXdmfWriter"):
        samples.append({"ext": ".xdmf", "label": "XDMF", "file": "",
                        "kind": "volume", "note": "vtkXdmfWriter unavailable",
                        "expect_reader": READERS.get(".xdmf", ""),
                        "reader_known": hasattr(pvs, "XDMFReader")})
        return
    path = os.path.join(out_dir, "tiny.xdmf")
    w = vtk.vtkXdmfWriter()
    w.SetFileName(path)
    w.SetInputData(_image())
    try:
        w.Write()
        if os.path.isfile(path):
            add(".xdmf", "XDMF", path, kind="volume")
            return
        raise RuntimeError("no output file")
    except Exception as e:                             # noqa: BLE001
        samples.append({"ext": ".xdmf", "label": "XDMF", "file": "",
                        "kind": "volume", "note": "xdmf write failed: %s" % e,
                        "expect_reader": READERS.get(".xdmf", ""),
                        "reader_known": hasattr(pvs, "XDMFReader")})


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out_dir, exist_ok=True)
    samples = []
    here = os.path.dirname(os.path.abspath(__file__))

    def add(ext, label, path, kind="geometry"):
        rname = READERS.get(ext, "")
        samples.append({"ext": ext, "label": label, "file": path,
                        "kind": kind, "expect_reader": rname,
                        "reader_known": (not rname) or hasattr(pvs, rname)})

    image = os.path.join(out_dir, "tiny.vti")
    _write_xml(vtk.vtkXMLImageDataWriter, _image(), image)
    add(".vti", "XMLImageData", image)

    ugrid = os.path.join(out_dir, "tiny.vtu")
    _write_xml(vtk.vtkXMLUnstructuredGridWriter, _ugrid(), ugrid)
    add(".vtu", "XMLUnstructuredGrid", ugrid)

    tri = os.path.join(out_dir, "tiny.vtp")
    _write_xml(vtk.vtkXMLPolyDataWriter, _tri(), tri)
    add(".vtp", "XMLPolyData", tri)

    sgrid = os.path.join(out_dir, "tiny.vts")
    _write_xml(vtk.vtkXMLStructuredGridWriter, _struct(), sgrid)
    add(".vts", "XMLStructuredGrid", sgrid)

    rgrid = os.path.join(out_dir, "tiny.vtr")
    _write_xml(vtk.vtkXMLRectilinearGridWriter, _rect(), rgrid)
    add(".vtr", "XMLRectilinearGrid", rgrid)

    legacy = os.path.join(out_dir, "tiny.vtk")
    w = vtk.vtkDataSetWriter()
    w.SetFileName(legacy)
    w.SetInputData(_ugrid())
    w.SetFileTypeToASCII()
    w.Write()
    add(".vtk", "LegacyDataSet", legacy)

    vtm = os.path.join(out_dir, "tiny.vtm")
    _write_xml(vtk.vtkXMLMultiBlockDataWriter, _multiblock(), vtm)
    add(".vtm", "XMLMultiBlock", vtm, kind="composite")

    for ext, writer_cls in ((".stl", vtk.vtkSTLWriter),
                            (".ply", vtk.vtkPLYWriter),
                            (".obj", vtk.vtkOBJWriter)):
        path = os.path.join(out_dir, "tiny" + ext)
        _write_xml(writer_cls, _tri(), path)
        add(ext, ext.lstrip(".").upper(), path)

    csv = os.path.join(out_dir, "tiny.csv")
    cw = vtk.vtkDelimitedTextWriter()
    cw.SetFileName(csv)
    cw.SetInputData(_table())
    cw.SetFieldDelimiter(",")
    cw.Write()
    add(".csv", "DelimitedText", csv, kind="table")

    f0 = os.path.join(out_dir, "frame0.vtu")
    f1 = os.path.join(out_dir, "frame1.vtu")
    _write_xml(vtk.vtkXMLUnstructuredGridWriter, _ugrid(), f0)
    u2 = _ugrid()
    a = u2.GetPointData().GetArray("u")
    for i in range(a.GetNumberOfTuples()):
        a.SetTuple1(i, float(i * 2))
    _write_xml(vtk.vtkXMLUnstructuredGridWriter, u2, f1)
    pvd = os.path.join(out_dir, "tiny.pvd")
    _write_text(pvd, (
        '<?xml version="1.0"?>\n'
        '<VTKFile type="Collection" version="0.1" '
        'byte_order="LittleEndian">\n'
        '<Collection>\n'
        '<DataSet timestep="0.0" group="" part="0" file="frame0.vtu"/>\n'
        '<DataSet timestep="1.0" group="" part="0" file="frame1.vtu"/>\n'
        '</Collection>\n</VTKFile>\n'))
    add(".pvd", "PVDCollection", pvd, kind="collection")

    pvbin = os.path.dirname(os.path.dirname(sys.executable or ""))
    pv_examples = os.path.join(pvbin, "examples") if pvbin else ""
    ex2 = _find_example([
        os.path.join(pv_examples, "disk_out_ref.ex2"),
        os.path.join(here, "_ex2_sample.ex2"),
    ])
    if ex2:
        dst = os.path.join(out_dir, "tiny.ex2")
        shutil.copyfile(ex2, dst)
        add(".ex2", "ExodusII", dst, kind="volume")
    else:
        samples.append({"ext": ".ex2", "label": "ExodusII", "file": "",
                        "kind": "volume", "note": "no example ex2 found",
                        "expect_reader": READERS.get(".ex2", ""),
                        "reader_known": (not READERS.get(".ex2", ""))
                        or hasattr(pvs, READERS.get(".ex2", ""))})
    bake = _find_example([os.path.join(pv_examples, "bake.e")])
    if bake:
        dst = os.path.join(out_dir, "tiny.e")
        shutil.copyfile(bake, dst)
        add(".e", "ExodusII", dst, kind="volume")
    else:
        samples.append({"ext": ".e", "label": "ExodusII", "file": "",
                        "kind": "volume", "note": "no example .e found",
                        "expect_reader": READERS.get(".e", ""),
                        "reader_known": (not READERS.get(".e", ""))
                        or hasattr(pvs, READERS.get(".e", ""))})
    _add_xdmf(out_dir, samples, add)

    try:
        from pvjob_pvdata import run_inspect
    except Exception as e:                             # noqa: BLE001
        for s in samples:
            if s.get("file"):
                s["status"] = "error"
                s["error"] = "pvjob_pvdata import failed: %s" % e
    else:
        for s in samples:
            fp = s.get("file")
            if not fp or not os.path.isfile(fp):
                s["status"] = "skip"
                continue
            try:
                r = run_inspect({"file_path": fp})
            except Exception as e:                     # noqa: BLE001
                s["status"] = "error"
                s["error"] = repr(e)[:300]
                continue
            s["status"] = "ok"
            s["reader"] = r.get("reader", "")
            s["points"] = r.get("points")
            s["cells"] = r.get("cells")
            s["timesteps"] = r.get("timesteps", [])
            pa = r.get("point_arrays", [])
            ca = r.get("cell_arrays", [])
            s["point_arrays"] = [a["name"] for a in pa][:12]
            s["cell_arrays"] = [a["name"] for a in ca][:12]
            s["n_point_arrays"] = len(pa)
            s["n_cell_arrays"] = len(ca)

    manifest = os.path.join(out_dir, "samples.json")
    with open(manifest, "w", encoding="utf-8") as f:
        json.dump({"samples": samples}, f, ensure_ascii=False, indent=1)
    print("SAMPLES_OK dir=%s n=%d" % (out_dir, len(samples)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
