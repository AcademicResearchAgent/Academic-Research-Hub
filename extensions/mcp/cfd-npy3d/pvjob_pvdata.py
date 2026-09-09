#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
pvjob_pvdata.py -- ParaView job executor for the cfd_npy3d_mcp extension
(runs under pvpython.exe, same convention as the workspace's pv_job.py).

The MCP server runs in a plain Python interpreter and cannot `import paraview`.
Every job is serialised into a JSON file, executed with:

    pvpython pvjob_pvdata.py <job.json>     ->  <job.json>.out.json

JOB TYPES:
  inspect  -- dataset metadata (reader, bounds, points/cells, timesteps,
              point/cell array names, components and ranges) for any ParaView-
              readable format (.vtu/.vtp/.vti/.vts/.vtr/.vtk/.vtm/.ex2/.pvd/
              .xdmf/.stl/.ply/.csv ...)
  points   -- extract one timestep's point cloud (xyz) plus one scalar/vector
              array (vector -> magnitude) from ANY ParaView dataset, sample it
              down to <= max_points and store as a compact .npz for the 3D
              scatter rendering done on the plain-Python side.
"""
from __future__ import annotations

import json
import math
import os
import sys
import traceback

try:
    from vtk import vtkObject
    vtkObject.GlobalWarningDisplayOff()
except Exception:                                     # noqa: BLE001
    pass

from paraview import simple as pvs
from paraview import servermanager as sm
from vtk.util.numpy_support import vtk_to_numpy
import numpy as np

# --------------------------------------------------------------------------- #
# readers: 与主 pv_job.py 同源 + 常见格式兜底
# --------------------------------------------------------------------------- #
READERS = {
    ".vti":  "XMLImageDataReader",
    ".vtu":  "XMLUnstructuredGridReader",
    ".vtp":  "XMLPolyDataReader",
    ".vts":  "XMLStructuredGridReader",
    ".vtr":  "XMLRectilinearGridReader",
    ".pvti": "XMLPImageDataReader",
    ".pvtu": "XMLPUnstructuredGridReader",
    ".pvtp": "XMLPPolyDataReader",
    ".vtm":  "XMLMultiBlockDataReader",
    ".vtmb": "XMLMultiBlockDataReader",
    ".vtk":  "LegacyVTKReader",
    ".stl":  "STLReader",
    ".ply":  "PLYReader",
    ".obj":  "OBJReader",
    ".csv":  "CSVReader",
    ".ex2":  "ExodusIIReader",
    ".exo":  "ExodusIIReader",
    ".e":    "ExodusIIReader",
    ".pvd":  "PVDReader",
    ".xdmf": "XDMFReader",
    ".xmf":  "XDMFReader",
}


def make_producer(params):
    fp = params.get("file_path")
    if not fp:
        raise RuntimeError("points/inspect need a file_path")
    if not os.path.exists(fp):
        raise RuntimeError("file not found: %s" % fp)
    ext = os.path.splitext(fp)[1].lower()
    name = READERS.get(ext)
    if name:
        cls = getattr(pvs, name)
        # PV >= 6: LegacyVTKReader/PVDReader 暴露 FileNames(列表) 而非 FileName
        for kwargs in ({"FileName": fp}, {"FileNames": [fp]}):
            try:
                return cls(**kwargs)
            except Exception:                          # noqa: BLE001
                continue
        raise RuntimeError("reader '%s' 无法接收文件参数" % name)
    try:
        return pvs.OpenDataFile(fp)
    except Exception as e:                            # noqa: BLE001
        raise RuntimeError("no reader mapped for '%s'; OpenDataFile failed: %s"
                           % (ext, e))


# --------------------------------------------------------------------------- #
# inspect
# --------------------------------------------------------------------------- #
def _arr_list(ai):
    out = []
    try:
        n = int(ai.GetNumberOfArrays())
    except Exception:                                 # noqa: BLE001
        return out
    for i in range(n):
        try:
            a = ai.GetArrayInformation(i)
            comps = int(a.GetNumberOfComponents())
            ranges = []
            for c in range(comps):
                r = [float(v) for v in a.GetComponentRange(c)]
                if any(not math.isfinite(v) for v in r):
                    r = [0.0, 1.0]
                ranges.append(r)
            out.append({"name": a.GetName(), "components": comps, "ranges": ranges})
        except Exception:                              # noqa: BLE001
            continue
    return out


def run_inspect(params):
    producer = make_producer(params)
    try:
        producer.UpdatePipeline()
    except Exception:                                  # noqa: BLE001
        pass
    di = producer.GetDataInformation()
    d = {}
    try:
        b = [float(v) for v in di.GetBounds()]
        if len(b) == 6 and all(math.isfinite(v) and abs(v) < 1e250 for v in b):
            d["bounds"] = b
    except Exception:                                  # noqa: BLE001
        d["bounds"] = None
    try:
        d["points"] = int(di.GetNumberOfPoints())
        d["cells"] = int(di.GetNumberOfCells())
    except Exception:                                  # noqa: BLE001
        pass
    try:
        tr = di.GetTimeRange()
        if all(math.isfinite(v) and abs(v) < 1e250 for v in tr):
            d["time_range"] = [float(tr[0]), float(tr[1])]
    except Exception:                                  # noqa: BLE001
        pass
    try:
        d["timesteps"] = [float(v) for v in producer.TimestepValues]
    except Exception:                                  # noqa: BLE001
        d["timesteps"] = []
    for key, attr in (("point_arrays", "GetPointDataInformation"),
                      ("cell_arrays", "GetCellDataInformation")):
        try:
            d[key] = _arr_list(getattr(di, attr)())
        except Exception:                              # noqa: BLE001
            d[key] = []
    d["reader"] = producer.GetXMLName()
    return d


# --------------------------------------------------------------------------- #
# points (extract -> npz)
# --------------------------------------------------------------------------- #
def _iter_leaves(data):
    """Yields every leaf dataset of a (possibly composite) dataset."""
    if data is None:
        return
    if data.IsA("vtkCompositeDataSet"):
        try:
            it = data.NewIterator()
            try:
                it.InitTraversal()
                while not it.IsDoneWithTraversal():
                    for leaf in _iter_leaves(it.GetCurrentDataObject()):
                        yield leaf
                    it.GoToNextItem()
            finally:
                it.Delete()
        except Exception:                              # noqa: BLE001
            return
        return
    yield data


def _leaf_points_values(leaf, array_name):
    """Points (N,3) float32 + array magnitude (N,) float32 for one leaf.
    Returns (pts, values, comps, ok).  vtkImageData / vtkRectilinearGrid do not
    expose GetPoints(), so coordinates are rebuilt from origin/spacing/grids."""
    npts = int(leaf.GetNumberOfPoints())
    if npts <= 0:
        return None, None, 0, True
    pd = leaf.GetPointData()
    arr = pd.GetArray(array_name) if pd else None
    if arr is None:
        return None, None, 0, False          # this leaf lacks the array
    comps = int(arr.GetNumberOfComponents())
    # ---- coordinates ----------------------------------------------------- #
    pts = None
    gp = getattr(leaf, "GetPoints", None)
    if gp is not None:
        pobj = gp()
        if pobj is not None:
            pts = np.asarray(vtk_to_numpy(pobj.GetData()), dtype=np.float32)
    if pts is None:
        try:
            if leaf.IsA("vtkImageData"):
                o = np.asarray(leaf.GetOrigin(), dtype=np.float64)
                sp = np.asarray(leaf.GetSpacing(), dtype=np.float64)
                dim = [int(v) for v in leaf.GetDimensions()]
                ax = [o[k] + sp[k] * np.arange(dim[k], dtype=np.float64)
                      for k in range(3)]
                gx, gy, gz = np.meshgrid(*ax, indexing="ij")
                pts = np.stack([gx, gy, gz], axis=-1).reshape(-1, 3)
                pts = pts.astype(np.float32)
            elif leaf.IsA("vtkRectilinearGrid"):
                x = vtk_to_numpy(leaf.GetXCoordinates()).astype(np.float32)
                y = vtk_to_numpy(leaf.GetYCoordinates()).astype(np.float32)
                z = vtk_to_numpy(leaf.GetZCoordinates()).astype(np.float32)
                gx, gy, gz = np.meshgrid(x, y, z, indexing="ij")
                pts = np.stack([gx, gy, gz], axis=-1).reshape(-1, 3)
        except Exception:                              # noqa: BLE001
            pts = None
    if pts is None or pts.shape[0] != npts:
        return None, None, 0, False
    # ---- values (vector -> magnitude) ------------------------------------ #
    raw = vtk_to_numpy(arr)
    if comps > 1:
        val = np.sqrt((raw.astype(np.float64) ** 2).sum(axis=1))
    else:
        val = raw.astype(np.float64)
    return pts, val.astype(np.float32), comps, True


def _choose_assoc(producer, name, info):
    """Resolve requested array name to ('POINTS'|'CELLS', display_name, info).
    Falls back like the main pick_color()."""
    if name:
        for assoc, lst in (("POINTS", info.get("point_arrays", [])),
                           ("CELLS", info.get("cell_arrays", []))):
            for a in lst:
                if a["name"] == name or a["name"].lower() == str(name).lower():
                    return assoc, a["name"], a
    for assoc, lst in (("POINTS", info.get("point_arrays", [])),
                       ("CELLS", info.get("cell_arrays", []))):
        for a in lst:
            if a["components"] == 1:
                return assoc, a["name"], a
    for assoc, lst in (("POINTS", info.get("point_arrays", [])),
                       ("CELLS", info.get("cell_arrays", []))):
        if lst:
            a = lst[0]
            return assoc, a["name"], a
    raise RuntimeError("dataset exposes no colour-able arrays")


def run_points(params):
    out_npz = params.get("out_npz")
    if not out_npz:
        raise RuntimeError("points job needs an out_npz target")
    producer = make_producer(params)
    try:
        producer.UpdatePipeline()
    except Exception:                                  # noqa: BLE001
        pass

    # ---- timestep selection ----------------------------------------------- #
    timesteps = []
    try:
        timesteps = [float(v) for v in producer.TimestepValues]
    except Exception:                                  # noqa: BLE001
        pass
    t_index = int(params.get("timestep_index") or 0)
    time_val = None
    if timesteps:
        t_index = max(0, min(t_index, len(timesteps) - 1))
        time_val = timesteps[t_index]
        try:
            producer.UpdatePipeline(float(time_val))
        except Exception:                              # noqa: BLE001
            pass
    elif t_index != 0:
        raise RuntimeError("dataset has no timesteps (timestep_index ignored)")

    # quick info for association resolution
    di = producer.GetDataInformation()
    point_arrays = _arr_list(di.GetPointDataInformation())
    cell_arrays = _arr_list(di.GetCellDataInformation())
    assoc, aname, ameta = _choose_assoc(
        producer, params.get("array_name"),
        {"point_arrays": point_arrays, "cell_arrays": cell_arrays})

    # cell arrays -> point arrays via the standard filter
    target = producer
    if assoc == "CELLS":
        try:
            cf = pvs.CellDatatoPointData(Input=producer)
            cf.ProcessAllArrays = 1
            target = cf
            target.UpdatePipeline()
        except Exception as e:                          # noqa: BLE001
            raise RuntimeError("cell array '%s' needs conversion to point data, "
                               "which failed: %s" % (aname, e))

    data = sm.Fetch(target)
    if data is None:
        raise RuntimeError("reader returned no data")

    pts_all, val_all, comps = [], [], 0
    skipped = 0
    for leaf in _iter_leaves(data):
        p, v, c, ok = _leaf_points_values(leaf, aname)
        if not ok:
            skipped += 1
            continue
        pts_all.append(p)
        val_all.append(v)
        comps = max(comps, c)
    if not pts_all:
        raise RuntimeError("no leaf dataset carries array '%s'" % aname)
    pts = np.concatenate(pts_all, axis=0)
    val = np.concatenate(val_all, axis=0)
    del pts_all, val_all

    # ---- sanity (drop non-finite) ----------------------------------------- #
    fin = np.isfinite(pts).all(axis=1) & np.isfinite(val)
    removed = int((~fin).sum())
    if removed:
        pts, val = pts[fin], val[fin]
    if pts.shape[0] == 0:
        raise RuntimeError("no finite points remain after filtering")

    # ---- down-sample ------------------------------------------------------- #
    maxp = int(params.get("max_points") or 250000)
    orig_n = int(pts.shape[0])
    if orig_n > maxp:
        idx = np.random.default_rng(0).choice(orig_n, maxp, replace=False)
        pts, val = pts[idx], val[idx]

    os.makedirs(os.path.dirname(os.path.abspath(out_npz)), exist_ok=True)
    np.savez_compressed(out_npz, pts=pts.astype(np.float32),
                        val=val.astype(np.float32))
    vv = val[np.isfinite(val)]
    return {
        "npz": out_npz,
        "npts_orig": orig_n,
        "npts_saved": int(pts.shape[0]),
        "array_name": aname,
        "association": assoc,
        "components": comps,
        "vmin": float(np.min(vv)),
        "vmax": float(np.max(vv)),
        "time": time_val,
        "timestep_index": t_index,
        "timestep_count": len(timesteps),
        "skipped_blocks": skipped,
        "filtered_nonfinite": removed,
        "reader": producer.GetXMLName(),
    }


# --------------------------------------------------------------------------- #
# import2d (ParaView 数据 -> X/Y/Q .npy，供 npy3d_* 渲染规则网格曲面)
# --------------------------------------------------------------------------- #
def _parse_time_slice(spec, n):
    """'0' | '0-4' | 'all' -> frame index list (clamped)."""
    if n <= 1:
        return [0]
    s = str(spec or "").strip() or "0"
    if s == "all":
        return list(range(n))
    if "-" in s:
        a, _, b = s.partition("-")
        lo = int(a) if a.strip() else 0
        hi = int(b) if b.strip() else n - 1
        return list(range(max(0, lo), min(n - 1, hi) + 1))
    return [max(0, min(n - 1, int(s)))]


try:                                                 # noqa: E402
    from vtk import vtkPointLocator as _VPLoc
except Exception:                                    # noqa: BLE001
    try:
        import vtkCommonDataModel as _cdm
        _VPLoc = _cdm.vtkPointLocator
    except Exception:                                # noqa: BLE001
        _VPLoc = None


def _pd_array(dobj, aname):
    """Point array by name (fallback: cell array)."""
    pd = dobj.GetPointData()
    arr = pd.GetArray(aname) if pd else None
    if arr is None:
        cd = dobj.GetCellData()
        arr = cd.GetArray(aname) if cd else None
    if arr is None:
        raise RuntimeError("dataset 中没有数组 '%s'" % aname)
    return arr


def _magnitude(raw):
    arr = np.asarray(raw)
    if arr.ndim == 2 and arr.shape[1] > 1:
        return np.sqrt((arr.astype(np.float64) ** 2).sum(axis=1))
    return arr.astype(np.float64)


def _sampler_structured(leaf, aname):
    """2D structural grids -> direct reshape (no resampling).

    Returns (X, Y, take, method) or (None, ...) when leaf is not structural.
    X/Y are (H, W) = (ny, nx) grids; x varies along axis1 (W), y along axis0 (H).
    """
    nx = ny = 0
    method = ""
    X = Y = None
    if leaf.IsA("vtkImageData"):
        nx, ny, nz = (int(v) for v in leaf.GetDimensions())
        if nz > 1:
            raise RuntimeError(
                "vtkImageData z 方向 %d 层，属三维体积场；导入仅支持 x-y 平面 2D 场"
                % nz)
        o = np.asarray(leaf.GetOrigin(), dtype=np.float64)
        sp = np.asarray(leaf.GetSpacing(), dtype=np.float64)
        xc = o[0] + sp[0] * np.arange(nx, dtype=np.float64)
        yc = o[1] + sp[1] * np.arange(ny, dtype=np.float64)
        X, Y = np.meshgrid(xc, yc)
        method = "vtkImageData 保持原网格直导 (%dx%d)" % (nx, ny)
    elif leaf.IsA("vtkRectilinearGrid"):
        xc = vtk_to_numpy(leaf.GetXCoordinates()).astype(np.float64)
        yc = vtk_to_numpy(leaf.GetYCoordinates()).astype(np.float64)
        zc = vtk_to_numpy(leaf.GetZCoordinates())
        if zc.size > 1:
            raise RuntimeError(
                "vtkRectilinearGrid z 方向 %d 层，属三维体积场；导入仅支持 x-y 平面 2D 场"
                % zc.size)
        nx, ny = int(xc.size), int(yc.size)
        X, Y = np.meshgrid(xc, yc)
        method = "vtkRectilinearGrid 保持原网格直导 (%dx%d)" % (nx, ny)
    elif leaf.IsA("vtkStructuredGrid"):
        nx, ny, nz = (int(v) for v in leaf.GetDimensions())
        if nz > 1:
            raise RuntimeError(
                "vtkStructuredGrid z 方向 %d 层，属三维体积场；导入仅支持 x-y 平面 2D 场"
                % nz)
        coords = np.asarray(vtk_to_numpy(leaf.GetPoints().GetData()),
                            dtype=np.float64).reshape(ny, nx, 3)
        X, Y = coords[:, :, 0], coords[:, :, 1]
        method = "vtkStructuredGrid 保持贴体网格直导 (%dx%d)" % (nx, ny)
    else:
        return None
    if nx < 1 or ny < 1:
        raise RuntimeError("结构化网格维度非法: %dx%d" % (nx, ny))

    def take(d2):
        arr = _pd_array(d2, aname)
        v = _magnitude(vtk_to_numpy(arr))
        if v.size != nx * ny:
            raise RuntimeError("数组长度 %d 与网格 %dx%d 不一致"
                               % (v.size, nx, ny))
        return v.reshape(ny, nx).astype(np.float32)

    return X.astype(np.float32), Y.astype(np.float32), take, method


def _sampler_nearest(leaf, aname, sample_w, sample_h):
    """Non-structural 2D data -> regular WxH grid via nearest-point lookup.

    Points outside the data hull (dist > 1.5 pixel diagonal) become NaN.
    """
    if _VPLoc is None:
        raise RuntimeError("vtkPointLocator 不可用，无法重采样非结构化数据")
    npts = int(leaf.GetNumberOfPoints())
    if npts <= 0:
        raise RuntimeError("数据集没有点")
    b = [float(v) for v in leaf.GetBounds()]
    x0, x1, y0, y1, z0, z1 = b
    xspan, yspan = x1 - x0, y1 - y0
    if sample_w > 0 and sample_h > 0:
        W, H = int(sample_w), int(sample_h)
    else:
        long_ = 320
        if xspan >= yspan:
            W = long_
            H = max(2, int(round(long_ * yspan / xspan))) if yspan > 0 else 2
        else:
            H = long_
            W = max(2, int(round(long_ * xspan / yspan))) if xspan > 0 else 2
    W, H = min(4096, max(2, W)), min(4096, max(2, H))
    xc = np.linspace(x0, x1, W)
    yc = np.linspace(y0, y1, H)
    X, Y = np.meshgrid(xc, yc)
    zc = 0.5 * (z0 + z1)

    loc = _VPLoc()
    loc.SetDataSet(leaf)
    loc.BuildLocator()
    gx, gy = X.ravel(), Y.ravel()
    ids = np.empty(gx.size, dtype=np.int64)
    for i in range(gx.size):
        ids[i] = loc.FindClosestPoint([float(gx[i]), float(gy[i]), zc])
    pts = np.asarray(vtk_to_numpy(leaf.GetPoints().GetData()),
                     dtype=np.float64)
    dx = (x1 - x0) / (W - 1) if W > 1 else 1.0
    dy = (y1 - y0) / (H - 1) if H > 1 else 1.0
    tol = 1.5 * math.hypot(dx, dy)
    gp = np.stack([gx, gy, np.full_like(gx, zc)], axis=1)
    valid = ids >= 0
    d = np.full(gx.size, np.inf, dtype=np.float64)
    if valid.any():
        d[valid] = np.sqrt(((gp[valid] - pts[ids[valid]]) ** 2).sum(axis=1))
    mask = d <= tol

    def take(d2):
        arr = _pd_array(d2, aname)
        v = _magnitude(vtk_to_numpy(arr))
        if v.size != npts:
            raise RuntimeError("数组长度 %d 与点数 %d 不一致" % (v.size, npts))
        q = np.full(gx.size, np.nan, dtype=np.float64)
        q[mask] = v[ids[mask]]
        return q.reshape(H, W).astype(np.float32)

    method = "最近点重采样 %dx%d (非结构化/多块合并)" % (W, H)
    return X.astype(np.float32), Y.astype(np.float32), take, method


def run_import2d(params):
    """Import an x-y planar 2D field from ANY ParaView-readable file into
    X/Y/Q .npy under out_dir (protocol: X/Y (H,W) [or (T,H,W)], Q (H,W)
    [single frame] / (T,H,W) [multi frame])."""
    out_dir = params.get("out_dir")
    if not out_dir:
        raise RuntimeError("import2d job needs an out_dir target")
    producer = make_producer(params)
    try:
        producer.UpdatePipeline()
    except Exception:                                  # noqa: BLE001
        pass
    timesteps = []
    try:
        timesteps = [float(v) for v in producer.TimestepValues]
    except Exception:                                  # noqa: BLE001
        pass
    idxs = _parse_time_slice(params.get("time_slice"), len(timesteps))

    di = producer.GetDataInformation()
    point_arrays = _arr_list(di.GetPointDataInformation())
    cell_arrays = _arr_list(di.GetCellDataInformation())
    assoc, aname, ameta = _choose_assoc(
        producer, params.get("array_name"),
        {"point_arrays": point_arrays, "cell_arrays": cell_arrays})

    # composite data -> single dataset; cell arrays -> point arrays
    target = producer
    d0 = sm.Fetch(producer)
    if d0 is not None and d0.IsA("vtkCompositeDataSet"):
        try:
            merged = pvs.MergeBlocks(Input=producer)
            target = merged
        except Exception as e:                         # noqa: BLE001
            raise RuntimeError("多块(composite)数据合并失败: %s" % e)
    if assoc == "CELLS":
        try:
            cf = pvs.CellDatatoPointData(Input=target)
            cf.ProcessAllArrays = 1
            target = cf
        except Exception as e:                         # noqa: BLE001
            raise RuntimeError("CELL 数组转 POINT 失败: %s" % e)

    X = Y = None
    take = None
    method = ""
    H = W = 0
    qs = []
    times = []
    first_nan = 0.0
    for fi in idxs:
        tv = None
        if timesteps:
            tv = timesteps[fi]
            try:
                producer.UpdatePipeline(float(tv))
            except Exception:                          # noqa: BLE001
                pass
        target.UpdatePipeline()
        data = sm.Fetch(target)
        if data is None:
            raise RuntimeError("reader 未返回数据")
        if data.IsA("vtkTable"):
            raise RuntimeError(
                "vtkTable（表格/CSV 类）无法结构化导入；请用 pvdata_inspect 检视")
        b = [float(v) for v in data.GetBounds()]
        xspan, yspan, zspan = b[1] - b[0], b[3] - b[2], b[5] - b[4]
        ztol = max(1e-6, 1e-3 * max(xspan, yspan, 1e-12))
        if zspan > ztol:
            raise RuntimeError(
                "数据在 z 方向有厚度 (span=%.6g > %.6g)，属三维体积场；"
                "pvdata_import 只导入 x-y 平面 2D 场，三维数据请改用 "
                "pvdata_render_scatter3d / pvdata_render_animation" % (zspan, ztol))
        if X is None:
            X, Y, take, method = _sampler_structured(data, aname)
            if X is None:
                X, Y, take, method = _sampler_nearest(
                    data, aname,
                    int(params.get("sample_w") or 0),
                    int(params.get("sample_h") or 0))
            H, W = X.shape
        q = take(data)
        qs.append(q)
        times.append(tv)
        if len(qs) == 1:
            fq = q[np.isfinite(q)]
            first_nan = float(1.0 - (fq.size / float(q.size)) if q.size else 1.0)

    T = len(qs)
    X32, Y32 = X.astype(np.float32), Y.astype(np.float32)
    os.makedirs(out_dir, exist_ok=True)
    if T == 1:
        np.save(os.path.join(out_dir, "X.npy"), X32)
        np.save(os.path.join(out_dir, "Y.npy"), Y32)
        np.save(os.path.join(out_dir, "Q.npy"), qs[0])
    else:
        np.save(os.path.join(out_dir, "X.npy"),
                np.broadcast_to(X32, (T, H, W)).copy())
        np.save(os.path.join(out_dir, "Y.npy"),
                np.broadcast_to(Y32, (T, H, W)).copy())
        np.save(os.path.join(out_dir, "Q.npy"), np.stack(qs, axis=0))

    return {
        "reader": producer.GetXMLName(),
        "array_name": aname,
        "association": assoc,
        "components": int(ameta.get("components", 1)),
        "method": method,
        "W": int(W),
        "H": int(H),
        "frames": T,
        "time_indices": idxs,
        "times": times,
        "bounds": [float(v) for v in b],
        "nan_percent": round(first_nan * 100.0, 2),
        "out_dir": os.path.abspath(out_dir),
        "files": ["X.npy", "Y.npy", "Q.npy"],
        "timestep_count": len(timesteps),
    }


# --------------------------------------------------------------------------- #
def main():
    if len(sys.argv) < 2:
        print("USAGE: pvpython pvjob_pvdata.py <job.json>")
        return 2
    jobfile = sys.argv[1]
    outfile = jobfile + ".out.json"
    job = {}
    try:
        with open(jobfile, "r", encoding="utf-8") as f:
            job = json.load(f)
        params = job.get("params") or {}
        jt = job.get("type")
        if jt == "inspect":
            res = run_inspect(params)
        elif jt == "points":
            res = run_points(params)
        elif jt == "import2d":
            res = run_import2d(params)
        else:
            raise ValueError("unknown job type: %r" % jt)
        payload = {"ok": True, "type": jt, "result": res}
    except Exception:                                  # noqa: BLE001
        payload = {"ok": False, "type": job.get("type"),
                   "error": traceback.format_exc(limit=25)}
    with open(outfile, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    print("DONE")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
