#!/usr/bin/env pvpython
# -*- coding: utf-8 -*-
"""枚举本机 ParaView 支持的全部 *Reader（只读 proxy XML 定义，不实例化任何
reader，避免个别 reader 构造触发崩溃），输出 JSON 权威清单。

用法（在 pvpython 下运行）：
    pvpython checks/export_paraview_readers.py --out config/paraview_readers.json

pvdata-import 技能 / pvdata_inspect 按此清单 + OpenDataFile 兜底，从而支持
"ParaView 支持的所有类型数据"。
"""
from __future__ import annotations

import argparse
import json

from paraview import servermanager as sm
from paraview import simple as pvs


def _get_definition(group, name):
    """vtkSMProxyManager::GetProxyDefinition -> vtkPVXMLElement or None."""
    try:
        pm = sm.ProxyManager()
        return pm.GetProxyDefinition(group, name)
    except Exception:                                    # noqa: BLE001
        return None


def _nested(el, tag):
    try:
        return el.FindNestedElement(tag)
    except Exception:                                    # noqa: BLE001
        return None


def _attr(el, key):
    try:
        return (el.GetAttribute(key) if el is not None else None) or ""
    except Exception:                                    # noqa: BLE001
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="config/paraview_readers.json")
    args = ap.parse_args()

    readers: dict = {}
    names = sorted(n for n in dir(pvs)
                   if n.endswith("Reader") and not n.startswith("_"))
    for nm in names:
        try:
            hints = None
            try:
                hints = _nested(_get_definition("sources", nm), "Hints")
            except Exception:                            # noqa: BLE001
                hints = None
            rf = _nested(hints, "ReaderFactory") if hints is not None else None
            readers[nm] = {
                "extensions": sorted(
                    x for x in _attr(rf, "extensions").split() if x),
                "description": _attr(rf, "file_description"),
            }
        except Exception:                                # noqa: BLE001
            readers[nm] = {"extensions": [], "description": ""}

    try:
        from vtk import vtkVersion
        vtk_ver = vtkVersion.GetVTKVersion()
    except Exception:                                    # noqa: BLE001
        vtk_ver = "unknown"

    doc = {
        "generated_by": "checks/export_paraview_readers.py "
                        "(proxy XML definitions, no instantiation)",
        "vtk_version": vtk_ver,
        "summary": {
            "total_readers": len(readers),
            "with_extensions": sum(1 for r in readers.values()
                                   if r["extensions"]),
            "total_extensions": len({x for r in readers.values()
                                     for x in r["extensions"]}),
        },
        "note": "pvdata_import/pvdata_inspect 对未列入显式映射的扩展名使用 "
                "OpenDataFile 自动探测兜底；本清单为 ParaView 官方 reader 全集。",
        "readers": readers,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print("WROTE %s: %d readers, %d extensions"
          % (args.out, doc["summary"]["total_readers"],
             doc["summary"]["total_extensions"]))


if __name__ == "__main__":
    main()
