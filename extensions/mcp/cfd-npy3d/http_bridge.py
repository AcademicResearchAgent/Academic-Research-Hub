# -*- coding: utf-8 -*-
"""http_bridge.py —— cfd-npy3d 的 OpenAPI(HTTP) 工具服务器（纯标准库，零依赖）。

供 Open WebUI 0.11.x 的 tool_server（type=openapi）直接注册使用：
  - GET  /openapi.json       反射 registry 的 8 个工具契约生成 OpenAPI 3 spec
  - POST /{operationId}      执行对应 handler（body 为 JSON 参数），返回 Markdown
  - POST /cfd_list_files     列出数据目录下文件（辅助 LLM 发现可渲染的数据）
  - GET  /files/{path...}    静态服务渲染产物（PNG/GIF），供聊天内嵌展示
  - GET  /viewer              Web 可视化工作台（数据导入 + WebGL 实时物理图像渲染引擎）
  - GET  /viewer/launch       弹出式启动页（在浏览器中弹出独立渲染新界面）
  - POST /api/*               工作台数据面：formats/datasets/import/series/export/paper

本服务是「技能后端」而非可自由浏览的网站：查看器页面与 /api/* 只对携带共享令牌
（?t=<token> 或 X-Bridge-Token 头，令牌由 webviz.bridge_token() 与技能进程共享）
的请求开放，未授权访问返回「技能专用」提示页。

启动（任意 python3，依赖 numpy/matplotlib 的 Anaconda 环境）：
  set NPY3D_OUT_ROOT=<产物根>   （缺省 <pkg>/../output）
  set PARAVIEW_PVPYTHON=<pvpython.exe>
  set CFD_BRIDGE_PUBLIC_BASE=<对外基址，跨机访问时用>
  python http_bridge.py --host 127.0.0.1 --port 8765
"""
from __future__ import annotations

import hmac
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import handlers
import registry
import webviz

OUT_ROOT = os.path.normpath(registry.OUT_ROOT)
HOST = "127.0.0.1"
PORT = int(os.environ.get("CFD_BRIDGE_PORT", "8765"))
_PUBLIC_BASE = "http://%s:%d" % (HOST, PORT)

# 技能共享令牌：本服务是「技能后端」而非可自由浏览的网站，查看器页面与 /api/*
# 只对携带此令牌的请求开放；令牌由 webviz.bridge_token() 与技能进程共享。
TOKEN = webviz.bridge_token()

# 静态服务的查看器资源后缀白名单（禁止目录穿越之外的任意文件读取）
_VIEWER_EXTS = {".html", ".js", ".css", ".json", ".svg", ".png", ".ico", ".map"}

# 未授权访问查看器页面时返回的提示页（不再像公开站点那样直接给出工作台）
_GATE_PAGE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>科研智能体工作站 · 技能专用渲染后端</title>
<style>
:root{color-scheme:light dark}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
 background:#f4f5f7;color:#1f2328;font:14px/1.7 -apple-system,"Segoe UI",Roboto,"Microsoft YaHei",sans-serif}
@media (prefers-color-scheme:dark){body{background:#14161a;color:#e6e8eb}}
.card{width:min(540px,92vw);padding:28px 28px 22px;border-radius:16px;
 background:rgba(255,255,255,.92);border:1px solid rgba(0,0,0,.08);
 box-shadow:0 10px 30px rgba(0,0,0,.08)}
@media (prefers-color-scheme:dark){.card{background:#1b1e23;border-color:rgba(255,255,255,.1)}}
.badge{display:inline-block;margin-bottom:12px;padding:3px 10px;border-radius:999px;
 font-size:11px;color:#0a7d5a;background:rgba(16,163,127,.12)}
h1{margin:0 0 10px;font-size:16px;font-weight:600}
p{margin:0 0 8px;color:#5b636e;font-size:12.5px}
@media (prefers-color-scheme:dark){p{color:#9aa3ae}}
code{background:rgba(0,0,0,.06);padding:1px 6px;border-radius:6px}
@media (prefers-color-scheme:dark){code{background:rgba(255,255,255,.1)}}
</style></head><body><div class="card">
<div class="badge">技能专用后端</div>
<h1>该渲染界面仅由技能调用打开</h1>
<p>这是 CFD 物理图像渲染引擎的本地后端，不作为独立网站对外浏览。</p>
<p>请在科研智能体工作站中说「用 CFD Web 可视化打开我的数据」，由
<code>cfd-web-visualization</code> 技能唤起独立渲染窗口。</p>
</div></body></html>"""


_TYPE_MAP = {"string": "string", "integer": "integer",
             "number": "number", "boolean": "boolean"}


def _arg_schema(arg: dict) -> dict:
    s: dict = {"type": _TYPE_MAP.get(arg.get("type", "string"), "string")}
    if arg.get("description"):
        s["description"] = arg["description"]
    if arg.get("enum"):
        s["enum"] = arg["enum"]
    if arg.get("default") is not None:
        s["default"] = arg["default"]
    if arg.get("items"):
        s["items"] = arg["items"]
    return s


def _tool_json_schema(spec: dict) -> dict:
    props, required = {}, []
    for a in spec.get("arguments", []):
        props[a["name"]] = _arg_schema(a)
        if a.get("required"):
            required.append(a["name"])
    return {"type": "object", "properties": props,
            "required": required, "additionalProperties": False}


def _build_openapi() -> dict:
    paths = {}
    for spec in registry.tool_specs():
        name = spec["name"]
        paths["/" + name] = {
            "post": {
                "operationId": name,
                "description": spec.get("description", name),
                "requestBody": {
                    "required": False,
                    "content": {"application/json": {
                        "schema": _tool_json_schema(spec)}},
                },
                "responses": {"200": {"description": "markdown 文本结果"}},
            }
        }
    paths["/cfd_list_files"] = {
        "post": {
            "operationId": "cfd_list_files",
            "description": (
                "列出数据目录 data_dir（缺省为实验数据导入目录）下可渲染的数据文件："
                "npy 数据集目录 / vtk/vtu/vti/vts/vtr/vtp/ex2/vtm/pvd/xdmf/stl/ply/obj/csv 等。"
                "用于先发现有哪些数据，再决定用哪个渲染工具。"),
            "requestBody": {
                "required": False,
                "content": {"application/json": {
                    "schema": {"type": "object",
                               "properties": {
                                   "data_dir": {"type": "string",
                                                "description": "要列举的目录，缺省用导入目录"}},
                               }}},
            },
            "responses": {"200": {"description": "markdown 清单"}},
        }
    }
    return {
        "openapi": "3.0.0",
        "info": {
            "title": "cfd-npy-3d tool server",
            "version": registry.load_manifest().get("package_version", "1.2.0"),
            "description": "CFD 数据检视与三维可视化工具（npy3d 平面场 / ParaView 常见格式）。",
        },
        "paths": paths,
    }


_PUBLIC_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z]:[\\/][^\s`|\u4e00-\u9fff]+\.(?:png|gif|jpg|jpeg|webp))",
    re.IGNORECASE)


def _to_public_url(p: str) -> str:
    norm = os.path.normpath(p.replace("/", os.sep))
    root = OUT_ROOT
    try:
        rel = os.path.relpath(norm, root)
    except ValueError:
        return p
    if rel.startswith(".."):
        return p
    return _PUBLIC_BASE + "/files/" + rel.replace(os.sep, "/")


def _md_with_public_links(md: str) -> str:
    def repl(m):
        return _to_public_url(m.group(1))
    return _PUBLIC_RE.sub(repl, md)


_PV_EXT = (".vtk", ".vtu", ".vti", ".vts", ".vtr", ".vtp", ".ex2", ".vtm",
           ".pvd", ".xdmf", ".xmf", ".stl", ".ply", ".obj", ".csv")
_NPY_MARKERS = ("x.npy", "y.npy", "q.npy")


def _default_data_dir() -> str:
    env = os.environ.get("CFD_DATA_DIR")
    if env and os.path.isdir(env):
        return env
    cand = os.path.join(os.path.dirname(registry.BASE), "exp_data")
    if os.path.isdir(cand):
        return cand
    return cand


def _scan_data_dir(data_dir: str) -> list[tuple[str, str]]:
    if not data_dir or not os.path.isdir(data_dir):
        return []
    rows: list[tuple[str, str]] = []
    for root, dirs, files in os.walk(data_dir):
        dirs[:] = [d for d in dirs if not d.startswith((".", "_"))]
        for fn in sorted(files):
            low = fn.lower()
            full = os.path.join(root, fn)
            if low.endswith(_PV_EXT):
                rows.append(("paraview", full))
            elif low.endswith(".npy") and any(m in low for m in _NPY_MARKERS):
                rows.append(("npy", full))
    return rows


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "cfd-npy3d-bridge/1.0"

    def _send(self, code: int, body: bytes, ctype: str = "text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(body)

    def _json_body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            n = 0
        if n <= 0:
            return {}
        raw = self.rfile.read(n) if n else b"{}"
        try:
            obj = json.loads(raw.decode("utf-8"))
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}

    def _send_json(self, code: int, obj: dict):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        return self._send(code, body, "application/json; charset=utf-8")

    # ---------------------- 访问控制（技能专用后端） ---------------------- #
    def _provided_token(self) -> str:
        q = parse_qs(urlparse(self.path).query)
        tok = (q.get("t") or [""])[0]
        return tok or (self.headers.get("X-Bridge-Token", "") or "")

    def _authorized(self) -> bool:
        return hmac.compare_digest(self._provided_token(), TOKEN)

    def _deny_html(self):
        return self._send(403, _GATE_PAGE.encode("utf-8"), "text/html; charset=utf-8")

    def _deny_api(self):
        return self._send_json(403, {
            "error": "unauthorized",
            "hint": "此为技能后端接口，仅由科研智能体工作站的 CFD Web 可视化技能调用。"})

    # ---------------------- Web 可视化工作台 ---------------------- #
    def _serve_viewer(self, rel: str):
        """静态服务 webviewer/ 下的前端资源（白名单后缀，禁止目录穿越）。"""
        rel = rel.lstrip("/") or "index.html"
        if not os.path.splitext(rel)[1]:
            rel += ".html"                      # /viewer/launch -> launch.html
        if os.path.splitext(rel)[1].lower() not in _VIEWER_EXTS:
            return self._send(404, b"viewer asset not found")
        # 工作台页面（index/launch）仅对技能调用开放；静态子资源（js/css/…）不拦截，
        # 这样页面被授权打开后仍能正常加载其脚本与样式。
        if rel.lower().endswith(".html") and not self._authorized():
            return self._deny_html()
        root = os.path.normpath(webviz.VIEWER_DIR)
        full = os.path.normpath(os.path.join(root, rel.replace("/", os.sep)))
        if not full.startswith(root) or not os.path.isfile(full):
            return self._send(404, b"viewer asset not found")
        low = full.lower()
        ctype = ("text/html; charset=utf-8" if low.endswith(".html") else
                 "text/javascript; charset=utf-8" if low.endswith(".js") else
                 "text/css; charset=utf-8" if low.endswith(".css") else
                 "application/json; charset=utf-8" if low.endswith(".json") else
                 "image/svg+xml" if low.endswith(".svg") else
                 "application/octet-stream")
        with open(full, "rb") as f:
            return self._send(200, f.read(), ctype)

    def _api_formats(self):
        return self._send_json(200, webviz.load_formats())

    def _api_datasets(self):
        p = self._json_body()
        try:
            rows = webviz.list_datasets(p.get("data_dir"))
        except Exception as e:                                # noqa: BLE001
            return self._send_json(500, {"error": str(e)})
        return self._send_json(200, {
            "data_dir": p.get("data_dir") or webviz.default_data_dir(),
            "datasets": rows})

    def _api_import(self):
        p = self._json_body()
        try:
            rep = webviz.import_file(
                file_path=p.get("file_path"),
                filename=p.get("filename"),
                content_b64=p.get("content_b64"),
                case=p.get("case"),
                array_name=p.get("array_name"),
                time_slice=str(p.get("time_slice", "0")),
                sample_w=int(p.get("sample_w") or 0),
                sample_h=int(p.get("sample_h") or 0),
                convert=bool(p.get("convert", True)))
        except Exception as e:                                # noqa: BLE001
            return self._send_json(500, {"ok": False, "error": str(e)})
        return self._send_json(200, rep)

    def _api_series(self):
        p = self._json_body()
        try:
            payload = webviz.series_payload(
                dataset=p.get("dataset"),
                frame=int(p.get("frame") or 0),
                channel=int(p.get("channel") or 0),
                max_points=int(p.get("max_points") or webviz.DEFAULT_MAX_POINTS),
                data_dir=p.get("data_dir"))
        except Exception as e:                                # noqa: BLE001
            return self._send_json(500, {"error": str(e)})
        return self._send_json(200, payload)

    def _api_export_paper(self):
        p = self._json_body()
        try:
            res = webviz.export_paper(
                image_b64=p.get("image_b64"), image_path=p.get("image_path"),
                caption=p.get("caption") or "", label=p.get("label") or "",
                name=p.get("name"),
                width=p.get("width") or "\\linewidth")
        except Exception as e:                                # noqa: BLE001
            return self._send_json(500, {"error": str(e)})
        return self._send_json(200, res)

    _API_GET = {"/api/formats": "_api_formats"}
    _API_POST = {
        "/api/datasets": "_api_datasets",
        "/api/import": "_api_import",
        "/api/series": "_api_series",
        "/api/export/paper": "_api_export_paper",
    }

    def do_OPTIONS(self):
        self._send(204, b"")

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == "/openapi.json":
            body = json.dumps(_build_openapi(), ensure_ascii=False).encode("utf-8")
            return self._send(200, body, "application/json; charset=utf-8")
        if path in self._API_GET:
            if not self._authorized():
                return self._deny_api()
            return getattr(self, self._API_GET[path])()
        if path in ("/viewer", "/viewer/"):
            return self._serve_viewer("index.html")
        if path.startswith("/viewer/"):
            return self._serve_viewer(path[len("/viewer/"):])
        if path.startswith("/files/"):
            return self._serve_file(path[len("/files/"):])
        return self._send(404, b"not found")

    def do_POST(self):
        path = unquote(urlparse(self.path).path)
        if path == "/cfd_list_files":
            return self._list_files()
        if path in self._API_POST:
            if not self._authorized():
                return self._deny_api()
            return getattr(self, self._API_POST[path])()
        name = path.lstrip("/")
        for spec in registry.tool_specs():
            if spec["name"] == name:
                fn = getattr(handlers, name, None)
                if fn is None:
                    return self._send(404, b"handler missing")
                params = self._json_body()
                try:
                    out = fn(**params)
                except Exception as e:                       # noqa: BLE001
                    return self._send(500, ("调用失败: %s" % e).encode("utf-8"))
                if isinstance(out, dict):
                    out = out.get("content") or json.dumps(out, ensure_ascii=False)
                md = _md_with_public_links(str(out))
                return self._send(200, md.encode("utf-8"))
        return self._send(404, b"unknown tool: " + name.encode("utf-8"))

    def _list_files(self):
        params = self._json_body()
        data_dir = params.get("data_dir") or _default_data_dir()
        rows = _scan_data_dir(data_dir)
        if not rows:
            md = "数据目录未发现可渲染文件：`%s`\n（支持 vtk/vtu/vti/vts/vtr/vtp/ex2/vtm/pvd/xdmf/stl/ply/obj/csv/npy）" % data_dir
            return self._send(200, md.encode("utf-8"))
        lines = ["## 数据目录 `%s`" % data_dir, "",
                 "| 类型 | 文件 |", "| --- | --- |"]
        for kind, full in rows:
            lines.append("| %s | `%s` |" % (kind, full))
        return self._send(200, "\n".join(lines).encode("utf-8"))

    def _serve_file(self, rel: str):
        rel = rel.lstrip("/")
        # 产物根下以「.」开头的隐藏文件（如 .bridge_token 令牌）不对外服务
        if any(part.startswith(".") for part in rel.replace("\\", "/").split("/") if part):
            return self._send(404, b"file not found")
        full = os.path.normpath(os.path.join(OUT_ROOT, rel))
        if not full.startswith(OUT_ROOT) or not os.path.isfile(full):
            return self._send(404, b"file not found")
        low = full.lower()
        ctype = ("image/png" if low.endswith(".png") else
                 "image/gif" if low.endswith(".gif") else
                 "image/jpeg" if low.endswith((".jpg", ".jpeg")) else
                 "application/octet-stream")
        with open(full, "rb") as f:
            return self._send(200, f.read(), ctype)

    def log_message(self, *args):  # noqa: A003
        pass


def main():
    host = sys.argv[sys.argv.index("--host") + 1] if "--host" in sys.argv else HOST
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else PORT
    os.environ.setdefault("CFD_BRIDGE_PORT", str(port))
    if "--host" in sys.argv:
        os.environ.setdefault("CFD_BRIDGE_PUBLIC_BASE", "http://%s:%d" % (host, port))
    srv = ThreadingHTTPServer((host, port), _Handler)
    print("cfd-npy3d OpenAPI bridge -> http://%s:%d/openapi.json  (out_root=%s)"
          % (host, port, OUT_ROOT), flush=True)
    print("viewer (skill-only)    -> %s" % webviz.launcher_url(), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
