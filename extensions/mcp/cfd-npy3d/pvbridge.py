# -*- coding: utf-8 -*-
"""pvbridge —— 普通 Python 侧调用 pvpython 执行 pvjob_pvdata.py 的桥。

与主 paraview-mcp 相同的 job 约定（JSON in / out.json out），但 job 与导出
的 .npz 都放在本扩展包的 .run/ 目录，不动工作区的核心文件。
"""
from __future__ import annotations

import datetime
import glob
import json
import os
import shutil
import subprocess

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "config", "paraview.json")
PV_JOB = os.path.join(BASE, "pvjob_pvdata.py")
RUN_DIR = os.path.join(BASE, ".run")

# 内置兜底候选（config/paraview.json 未提供时使用）
_BUILTIN_CANDIDATES = [
    r"D:\Program Files\ParaView 6.0.1\bin\pvpython.exe",
    r"C:\Program Files\ParaView 6.0.1\bin\pvpython.exe",
]


def _config() -> dict:
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:                                  # noqa: BLE001
            return {}
    return {}


def _candidate_paths() -> list[str]:
    """config/paraview.json 的 pvpython.candidates（${VAR} 展开 + glob），
    其后追加环境变量/PATH 兜底。返回去重后的路径列表。"""
    cfg = _config()
    out: list[str] = []
    for c in (cfg.get("pvpython", {}).get("candidates") or []):
        e = os.path.expandvars(str(c)).strip()
        if not e:
            continue
        hits = glob.glob(e) if ("*" in e or "?" in e) else ([e] if e else [])
        for h in hits:
            if h not in out:
                out.append(h)
    for b in [os.environ.get("PARAVIEW_PVPYTHON"),
              os.path.join(os.environ.get("PARAVIEW_BIN", ""), "pvpython.exe"),
              shutil.which("pvpython")]:
        if b and b not in out:
            out.append(b)
    if not any(os.path.isfile(p) for p in out):
        for d in _BUILTIN_CANDIDATES + ["pvpython"]:
            if d not in out:
                out.append(d)
    return out


def job_timeout(default: int = 600) -> int:
    return int(_config().get("pvpython", {}).get("job_timeout_seconds")
               or default)


def find_pvpython() -> str:
    for c in _candidate_paths():
        if os.path.isfile(c):
            return c
    raise RuntimeError(
        "pvpython.exe not found. Set PARAVIEW_PVPYTHON, add ParaView's bin to "
        "PATH, or edit extensions/mcp/cfd-npy3d/config/paraview.json "
        "(pvpython.candidates).")


def available() -> bool:
    try:
        find_pvpython()
        return True
    except RuntimeError:
        return False


def run_job(job_type: str, params: dict, timeout: int | None = None) -> dict:
    """Execute one pvpython job, return its result dict (raises on error)."""
    pvpython = find_pvpython()
    timeout = job_timeout() if timeout is None else timeout
    os.makedirs(RUN_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    jobfile = os.path.join(RUN_DIR, f"pvdata_{job_type}_{stamp}_{os.getpid()}.json")
    outfile = jobfile + ".out.json"
    try:
        with open(jobfile, "w", encoding="utf-8") as f:
            json.dump({"type": job_type, "params": params}, f, ensure_ascii=False)
        proc = subprocess.run(
            [pvpython, PV_JOB, jobfile],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, timeout=timeout,
        )
        if not os.path.isfile(outfile):
            tail = ((proc.stdout or "")[-1500:] + "\n" + (proc.stderr or "")[-3000:])
            raise RuntimeError("pvpython produced no result file.\n" + tail)
        with open(outfile, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if not payload.get("ok"):
            raise RuntimeError("pvpython job failed:\n"
                               + str(payload.get("error", ""))[-4000:])
        return payload["result"]
    finally:
        try:
            if os.path.isfile(jobfile):
                os.remove(jobfile)
            if os.path.isfile(outfile):
                os.remove(outfile)
        except OSError:
            pass


def clean_run_dir():
    """清理导出的 .npz 临时文件（保留 .run 目录本身）。"""
    if not os.path.isdir(RUN_DIR):
        return
    for f in os.listdir(RUN_DIR):
        if f.endswith(".npz"):
            try:
                os.remove(os.path.join(RUN_DIR, f))
            except OSError:
                pass


def scratch_npz() -> str:
    os.makedirs(RUN_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return os.path.join(RUN_DIR, f"pts_{stamp}_{os.getpid()}.npz")
