# -*- coding: utf-8 -*-
"""cfd-npy3d「Web 可视化工作台」回归测试。

覆盖：格式清单单一事实源、数据集扫描、渲染载荷的 JSON 安全性（无 NaN/Inf）、
大网格降采样、数据导入（不支持格式 / 部分 npy / ParaView / 上传字节）、
论文插图导出（PNG + LaTeX 片段）、入口工具 handler 的输出结构，以及
「技能专用后端」的令牌门禁（查看器页面与 /api/* 仅对技能令牌开放）。

运行：
    python -m unittest discover -s tests -p test_cfd_npy3d_webviz.py -v
"""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "extensions" / "mcp" / "cfd-npy3d"
SAMPLE = EXT / "sample_data"

# 让导入的产物落到临时目录，避免污染仓库产物根（registry 在 import 时读该环境变量）
_TMP = tempfile.mkdtemp(prefix="npy3d_webviz_")
os.environ["NPY3D_OUT_ROOT"] = _TMP
sys.path.insert(0, str(EXT))

import handlers          # noqa: E402
import http_bridge       # noqa: E402
import webviz            # noqa: E402

# 1x1 透明 PNG，用于论文导出测试
PNG_1X1 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def _sample_npy_dir() -> str:
    rows = [r for r in webviz.list_datasets(str(SAMPLE)) if r["kind"] == "npy"]
    assert rows, "sample_data 中未发现 npy 数据集"
    return rows[0]["path"]


class FormatTests(unittest.TestCase):
    def test_supported_exts_cover_npy_and_paraview(self):
        exts = webviz.supported_exts()
        for e in (".npy", ".vtk", ".vtu", ".vti", ".vts", ".vtr", ".csv", ".stl"):
            self.assertIn(e, exts, e)

    def test_kind_of(self):
        self.assertEqual(webviz.kind_of("X.npy"), "npy")
        self.assertEqual(webviz.kind_of("a.VTU"), "paraview")
        self.assertEqual(webviz.kind_of(str(SAMPLE)), "npy")
        self.assertIsNone(webviz.kind_of("notes.docx"))

    def test_viewer_assets_present(self):
        for f in ("index.html", "viewer.js", "viewer.css", "formats.json", "launch.html"):
            self.assertTrue(os.path.isfile(os.path.join(webviz.VIEWER_DIR, f)), f)


class DatasetTests(unittest.TestCase):
    def test_scan_finds_npy_case_and_paraview_file(self):
        rows = webviz.list_datasets(str(SAMPLE))
        npy = [r for r in rows if r["kind"] == "npy"]
        pv = [r for r in rows if r["kind"] == "paraview"]
        self.assertTrue(npy, "未发现 npy 数据集")
        self.assertTrue(npy[0]["renderable"])
        self.assertEqual(len(npy[0]["grid"]), 2)
        self.assertTrue(any(r["path"].endswith("plane2d.vtk") for r in pv))

    def test_default_data_dir_is_absolute(self):
        self.assertTrue(os.path.isabs(webviz.default_data_dir()))

    def test_resolve_dataset_by_name_and_path(self):
        d = _sample_npy_dir()
        self.assertEqual(os.path.normpath(webviz.resolve_dataset(d, str(SAMPLE))),
                         os.path.normpath(d))
        self.assertEqual(os.path.normpath(webviz.resolve_dataset(os.path.basename(d), str(SAMPLE))),
                         os.path.normpath(d))


class PayloadTests(unittest.TestCase):
    def test_grid_payload_is_json_safe(self):
        p = webviz.series_payload(dataset=_sample_npy_dir(), frame=0, channel=0)
        self.assertEqual(p["kind"], "grid")
        self.assertEqual(len(p["x"]), len(p["y"]))
        self.assertEqual(len(p["y"]), len(p["z"]))
        self.assertEqual(p["axes"], ["X", "Y", "Q"])
        txt = json.dumps(p)                     # 不得含 NaN / Infinity
        self.assertNotIn("NaN", txt)
        self.assertNotIn("Infinity", txt)
        if "indices" in p:
            self.assertEqual(len(p["indices"]) % 3, 0)
            self.assertLess(max(p["indices"]), len(p["x"]))
            self.assertGreaterEqual(min(p["indices"]), 0)

    def test_downsampling_caps_point_count(self):
        p = webviz.series_payload(dataset=_sample_npy_dir(), frame=0,
                                  channel=0, max_points=300)
        self.assertLessEqual(len(p["x"]), 300)
        self.assertGreaterEqual(p["stride"], 1)

    def test_frame_and_channel_are_clipped(self):
        p = webviz.series_payload(dataset=_sample_npy_dir(), frame=9999, channel=9999)
        self.assertLess(p["frame"], p["frames"])
        self.assertLess(p["channel"], p["channels"])


class ImportTests(unittest.TestCase):
    def test_unsupported_extension_is_rejected(self):
        src = os.path.join(tempfile.mkdtemp(dir=_TMP), "notes.txt")
        Path(src).write_text("not data", encoding="utf-8")
        rep = webviz.import_file(file_path=src)
        self.assertFalse(rep["ok"])
        self.assertIn("不支持的扩展名", rep["message"])

    def test_partial_npy_reports_missing_fields(self):
        src = os.path.join(tempfile.mkdtemp(dir=_TMP), "Q.npy")
        np.save(src, np.zeros((4, 5)))
        rep = webviz.import_file(file_path=src, convert=False)
        self.assertFalse(rep["ok"])
        self.assertIn("X", rep["message"])
        self.assertIn("Y", rep["message"])

    def test_split_import_into_same_case_completes_npy_set(self):
        work = tempfile.mkdtemp(dir=_TMP)
        for name in ("X.npy", "Y.npy", "Q.npy"):
            np.save(os.path.join(work, name), np.zeros((4, 5)))
        # 分次导入：显式 case 复用同一目录，X/Y/Q 补齐后即可渲染
        rep = webviz.import_file(file_path=os.path.join(work, "Q.npy"), case="trio")
        self.assertFalse(rep["ok"])
        webviz.import_file(file_path=os.path.join(work, "X.npy"), case="trio")
        rep = webviz.import_file(file_path=os.path.join(work, "Y.npy"), case="trio")
        self.assertTrue(rep["ok"])
        self.assertTrue(rep["data_dir"].endswith("trio"))
        rows = [r for r in webviz.list_datasets(os.path.dirname(rep["data_dir"]))
                if r["path"] == rep["data_dir"]]
        self.assertTrue(rows and rows[0]["renderable"])

    def test_paraview_file_imported_as_point_cloud(self):
        rep = webviz.import_file(file_path=str(SAMPLE / "plane2d.vtk"), convert=False)
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["kind"], "paraview")
        self.assertTrue(os.path.isfile(rep["file"]))
        self.assertIn("pvdata_inspect", rep["next_tools"])

    def test_uploaded_bytes_are_written_verbatim(self):
        raw = b"# vtk DataFile Version 2.0"
        rep = webviz.import_file(filename="probe.vtk",
                                 content_b64=base64.b64encode(raw).decode("ascii"),
                                 convert=False)
        self.assertTrue(rep["ok"])
        with open(rep["file"], "rb") as f:
            self.assertEqual(f.read(), raw)


class PaperExportTests(unittest.TestCase):
    def test_export_writes_png_and_latex_snippet(self):
        res = webviz.export_paper(image_b64=PNG_1X1, caption="Instantaneous Q field.",
                                  label="wake_q", name="unit_test")
        self.assertTrue(os.path.isfile(res["image_path"]))
        self.assertIn("\\includegraphics", res["latex"])
        self.assertIn("fig:wake_q", res["latex"])
        self.assertIn("Instantaneous Q field.", res["latex"])
        self.assertTrue(res["url"].endswith(".png"))
        self.assertTrue(res["url"].startswith(webviz.viewer_base()))

    def test_export_requires_an_image(self):
        with self.assertRaises(ValueError):
            webviz.export_paper()


class ViewerEntryTests(unittest.TestCase):
    def test_handler_returns_entry_formats_and_url(self):
        md = handlers.npy3d_web_viewer(data_dir=str(SAMPLE))
        self.assertIn("/viewer", md)
        self.assertIn("支持的导入格式", md)
        self.assertIn(".vtu", md)
        self.assertIn("| npy |", md)

    def test_handler_with_file_path_reports_import(self):
        md = handlers.npy3d_web_viewer(file_path=str(SAMPLE / "plane2d.vtk"))
        self.assertIn("导入结果", md)
        self.assertIn("paraview", md)

    def test_paper_hint_is_opt_in(self):
        self.assertIn("导出到论文", handlers.npy3d_web_viewer(embed_in_paper=True))
        self.assertNotIn("导出到论文", handlers.npy3d_web_viewer(embed_in_paper=False))

    def test_viewer_url_carries_presets(self):
        url = webviz.viewer_url("E:/x", frame=3, channel=1, embed_in_paper=True)
        self.assertIn("/viewer?", url)
        self.assertIn("frame=3", url)
        self.assertIn("channel=1", url)
        self.assertIn("paper=1", url)
        self.assertNotIn("popup=1", url)

    def test_viewer_url_popup_flag(self):
        self.assertIn("popup=1", webviz.viewer_url("E:/x", popup=True))

    def test_launcher_url_points_to_popup_page(self):
        url = webviz.launcher_url("E:/x", frame=3, channel=1, embed_in_paper=True)
        self.assertIn("/viewer/launch?", url)
        self.assertIn("popup=1", url)
        self.assertIn("frame=3", url)
        self.assertIn("channel=1", url)
        self.assertIn("paper=1", url)

    def test_entry_url_switches_between_popup_and_tab(self):
        self.assertIn("/viewer/launch?", webviz.entry_url("E:/x"))
        self.assertIn("/viewer/launch?", webviz.entry_url("E:/x", open_in="popup"))
        self.assertIn("/viewer/launch?", webviz.entry_url("E:/x", open_in="new_window"))
        tab = webviz.entry_url("E:/x", open_in="tab")
        self.assertIn("/viewer?", tab)
        self.assertNotIn("/viewer/launch", tab)

    def test_handler_default_returns_popup_launcher(self):
        md = handlers.npy3d_web_viewer(dataset="NACA")
        self.assertIn("/viewer/launch?", md)
        self.assertIn("弹出独立渲染新界面", md)

    def test_handler_tab_mode_returns_viewer_page(self):
        md = handlers.npy3d_web_viewer(dataset="NACA", open_in="tab")
        self.assertIn("/viewer?", md)
        self.assertNotIn("/viewer/launch?", md)
        self.assertIn("在浏览器标签页中打开", md)


class SkillOnlyBackendTests(unittest.TestCase):
    """渲染服务是「技能后端」而非可浏览网站：入口 URL 带共享令牌，页面/接口校验令牌。"""

    def test_token_is_stable_and_shared_with_bridge(self):
        tok = webviz.bridge_token()
        self.assertTrue(tok)
        self.assertEqual(tok, webviz.bridge_token())        # 同一进程内稳定
        self.assertEqual(http_bridge.TOKEN, tok)            # 与桥服务进程同源

    def test_entry_urls_carry_token(self):
        tok = webviz.bridge_token()
        for url in (webviz.viewer_url("E:/x"), webviz.viewer_url("E:/x", popup=True),
                    webviz.launcher_url("E:/x"), webviz.entry_url("E:/x", open_in="tab")):
            self.assertIn("t=" + tok, url)

    def test_handler_markdown_exposes_tokenized_entry(self):
        md = handlers.npy3d_web_viewer(dataset="NACA", open_in="tab")
        self.assertIn("t=" + webviz.bridge_token(), md)

    def test_bridge_authorizes_only_matching_token(self):
        h = http_bridge._Handler.__new__(http_bridge._Handler)  # 不启动服务器
        h.headers = {}
        h.path = "/viewer?t=" + http_bridge.TOKEN
        self.assertTrue(h._authorized())
        h.path = "/viewer?t=wrong-token"
        self.assertFalse(h._authorized())
        h.path = "/viewer"
        self.assertFalse(h._authorized())
        h.headers = {"X-Bridge-Token": http_bridge.TOKEN}       # 也支持请求头
        self.assertTrue(h._authorized())

    def test_gate_page_states_skill_only(self):
        self.assertIn("技能专用后端", http_bridge._GATE_PAGE)
        self.assertIn("仅由技能调用打开", http_bridge._GATE_PAGE)

    def test_viewer_assets_carry_token_forwarding(self):
        js = (webviz.VIEWER_DIR and
              Path(webviz.VIEWER_DIR, "viewer.js").read_text(encoding="utf-8"))
        launch = Path(webviz.VIEWER_DIR, "launch.html").read_text(encoding="utf-8")
        self.assertIn("withToken", js)                       # /api 请求透传令牌
        self.assertIn("q.get('t')", launch)                  # 弹出窗口透传令牌


if __name__ == "__main__":
    unittest.main()
