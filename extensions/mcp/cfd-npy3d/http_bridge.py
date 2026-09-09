# -*- coding: utf-8 -*-
"""http_bridge.py —— cfd-npy3d 的 OpenAPI(HTTP) 工具服务器（纯标准库，零依赖）。

供 Open WebUI 0.11.x 的 tool_server（type=openapi）直接注册使用：
  - GET  /openapi.json       反射 registry 的 7 个工具契约生成 OpenAPI 3 spec
  - POST /{operationId}      执行对应 handler（body 为 JSON 参数），返回 Markdown
  - POST /cfd_list_files     列出数据目录下文件（辅助 LLM 发现可渲染的数据）
  - GET  /files/{path...}    静态服务渲染产物（PNG/GIF），供聊天内嵌展示

启动（任意 python3，依赖 numpy/matplotlib 的 Anaconda 环境）：
  set NPY3D_OUT_ROOT=<产物根>   （缺省 <pkg>/../output）
  set PARAVIEW_PVPYTHON=<pvpython.exe>
  python http_bridge.py --host 127.0.0.1 --port 8765
"""
from __future__ import annotations

import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

import handlers
import registry

OUT_ROOT = os.path.normpath(registry.OUT_ROOT)
HOST = "127.0.0.1"
PORT = int(os.environ.get("CFD_BRIDGE_PORT", "8765"))
_PUBLIC_BASE = "http://%s:%d" % (HOST, PORT)


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

    def do_OPTIONS(self):
        self._send(204, b"")

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == "/openapi.json":
            body = json.dumps(_build_openapi(), ensure_ascii=False).encode("utf-8")
            return self._send(200, body, "application/json; charset=utf-8")
        if path.startswith("/files/"):
            return self._serve_file(path[len("/files/"):])
        return self._send(404, b"not found")

    def do_POST(self):
        path = unquote(urlparse(self.path).path)
        if path == "/cfd_list_files":
            return self._list_files()
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
    srv = ThreadingHTTPServer((host, port), _Handler)
    print("cfd-npy3d OpenAPI bridge -> http://%s:%d/openapi.json  (out_root=%s)"
          % (host, port, OUT_ROOT), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
