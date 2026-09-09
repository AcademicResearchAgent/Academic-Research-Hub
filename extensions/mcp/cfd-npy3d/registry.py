# -*- coding: utf-8 -*-
"""registry.py —— cfd_npy3d_mcp 工具注册表（契约驱动层）。

参考 academic-research-skills 的「manifest + frontmatter 纪律」组织：
  - manifest.json            显式清单：列出全部工具文件与技能目录；
  - tools/<name>.json        每个工具一份数据化契约（名称/标题/描述/参数）；
  - checks/                  质量门：保证 契约 <-> 实现(handlers) <-> 技能文档 三方一致。

server.py 启动时按 registry 顺序自动注册工具；新增工具只需：加契约文件
+ 更新 manifest + 实现 handler + 过质量门，无需改 server 主体。
"""
from __future__ import annotations

import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.abspath(os.path.join(BASE, ".."))     # g:/mcp-
OUT_ROOT = os.environ.get("NPY3D_OUT_ROOT") or os.path.join(WORKSPACE, "output")

MANIFEST_PATH = os.path.join(BASE, "manifest.json")
TOOLS_DIR = os.path.join(BASE, "tools")
SKILLS_DIR = os.path.join(BASE, "skills")

ALLOWED_TYPES = {"string", "integer", "number", "boolean"}
ALLOWED_FAMILIES = {"npy3d", "pvdata"}
REQUIRED_SPEC_KEYS = ("name", "title", "description", "family",
                      "data_source", "requires_pvpython", "returns", "arguments")
REQUIRED_ARG_KEYS = ("name", "type", "required")


def load_manifest() -> dict:
    """读 manifest.json；异常向上抛（由校验层转成可读错误）。"""
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)


def tool_specs() -> list[dict]:
    """按 manifest 声明顺序返回每个工具的完整契约（附 _source 相对路径）。"""
    out = []
    for rel in load_manifest().get("tools", []):
        with open(os.path.join(BASE, rel), encoding="utf-8") as f:
            spec = json.load(f)
        spec["_source"] = rel
        out.append(spec)
    return out


def tool_names() -> list[str]:
    return [s["name"] for s in tool_specs()]


def skill_dirs() -> list[str]:
    """manifest 声明的技能目录绝对路径列表。"""
    m = load_manifest()
    return [os.path.join(BASE, s) for s in m.get("skills", [])]


def validate_registry() -> list[str]:
    """契约文件自身合法性校验；返回错误列表，空列表 = 通过。

    只校验“文件写得对不对”，不做契约与实现的交叉核对（那是
    checks/check_registry_consistency.py 的职责）。
    """
    errs: list[str] = []
    try:
        m = load_manifest()
    except Exception as e:                              # noqa: BLE001
        return ["manifest.json 读取失败: %s" % e]
    if m.get("schema_version") != 1:
        errs.append("manifest.schema_version 必须为 1")
    if m.get("server") != "cfd-npy-3d":
        errs.append("manifest.server 必须为 'cfd-npy-3d'")
    for rel in m.get("tools", []):
        p = os.path.join(BASE, rel)
        base = os.path.basename(rel)
        if not base.endswith(".json"):
            errs.append("工具文件 %s 必须以 .json 结尾" % rel)
        if not os.path.isfile(p):
            errs.append("工具文件缺失: %s" % rel)
            continue
        try:
            with open(p, encoding="utf-8") as f:
                spec = json.load(f)
        except Exception as e:                          # noqa: BLE001
            errs.append("%s 不是合法 JSON: %s" % (rel, e))
            continue
        if spec.get("name") != base[: -len(".json")]:
            errs.append("%s: spec.name(%s) 与文件名不一致"
                        % (rel, spec.get("name")))
        for k in REQUIRED_SPEC_KEYS:
            if k not in spec:
                errs.append("%s: 缺必填字段 %s" % (rel, k))
        if spec.get("family") not in ALLOWED_FAMILIES:
            errs.append("%s: family=%r 非法（允许 %s）"
                        % (rel, spec.get("family"), sorted(ALLOWED_FAMILIES)))
        for a in spec.get("arguments", []):
            for k in REQUIRED_ARG_KEYS:
                if k not in a:
                    errs.append("%s: 参数 %s 缺字段 %s"
                                % (rel, a.get("name"), k))
            if a.get("type") not in ALLOWED_TYPES:
                errs.append("%s: 参数 %s type=%r 非法（允许 %s）"
                            % (rel, a.get("name"), a.get("type"),
                               sorted(ALLOWED_TYPES)))
            if not isinstance(a.get("required"), bool):
                errs.append("%s: 参数 %s required 必须为布尔值"
                            % (rel, a.get("name")))
    for s in m.get("skills", []):
        if not os.path.isfile(os.path.join(BASE, s, "SKILL.md")):
            errs.append("技能 %s 缺失 SKILL.md" % s)
    # 去重保序
    seen, uniq = set(), []
    for e in errs:
        if e not in seen:
            seen.add(e)
            uniq.append(e)
    return uniq
