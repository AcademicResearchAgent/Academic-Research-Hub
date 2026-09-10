# -*- coding: utf-8 -*-
"""check_registry_consistency.py —— 契约 <-> 实现 <-> 技能文档 一致性质量门。

仿 academic-research-skills 的 check_*.py 模式：一个检查脚本一个主题，
可独立执行（`python checks/check_registry_consistency.py`），也提供
run() 供 server --selftest 集成。检查维度：

  1. registry 契约文件自身合法（manifest.json + tools/*.json）；
  2. manifest 声明的工具在 handlers 中全部有实现，且无“孤儿实现”；
  3. tools/*.json 参数契约与 handler 函数签名一致
     （参数名集合、必填/可选、默认值类型与取值）；
  4. manifest 声明的每个技能目录含合法 SKILL.md（frontmatter 含 name/description）；
  5. 每个工具至少被一个技能文档提及（文档不滞后于注册表）。

退出码：0=全部通过；1=存在不一致（打印明细）。
"""
from __future__ import annotations

import inspect
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import registry                       # noqa: E402


def _skill_texts() -> list[tuple[str, str]]:
    """返回 [(skill_dir, 该 skill 全部 .md 文本拼接), ...]。"""
    out = []
    for d in registry.skill_dirs():
        text = ""
        for root, _dirs, files in os.walk(d):
            for f in sorted(files):
                if f.lower().endswith((".md", ".markdown")):
                    p = os.path.join(root, f)
                    with open(p, encoding="utf-8") as fh:
                        text += "\n" + fh.read()
        out.append((os.path.basename(d), text))
    return out


def _check_frontmatter(dirname: str, text: str, lines: list[str]) -> None:
    m = re.match(r"^\s*---\s*\n(.*?)\n---", text, re.S)
    if not m:
        lines.append("CHECK FAIL: %s/SKILL.md 缺 yaml frontmatter (--- 包裹)"
                     % dirname)
        return
    fm = m.group(1)
    for key in ("name:", "description:"):
        if not re.search(r"^%s\s+.+" % key, fm, re.M):
            lines.append("CHECK FAIL: %s/SKILL.md frontmatter 缺字段 %s"
                         % (dirname, key.rstrip(":")))


def _check_signature(spec, fn, lines: list[str]) -> None:
    """tools/*.json 参数契约 <-> handler 函数签名。"""
    src = spec["_source"]
    params = inspect.signature(fn).parameters
    spec_args = {a["name"]: a for a in spec.get("arguments", [])}
    fn_names = {n for n, p in params.items()
                if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)}
    if set(spec_args) != fn_names:
        lines.append("CHECK FAIL: %s 参数契约 %s 与实现签名 %s 不一致"
                     % (src, sorted(spec_args), sorted(fn_names)))
        return
    for name, a in spec_args.items():
        p = params[name]
        required = p.default is inspect.Parameter.empty
        if a["required"] != required:
            lines.append("CHECK FAIL: %s 参数 %s required=%s 与签名默认值不一致"
                         % (src, name, a["required"]))
        if not a["required"] and p.default is not inspect.Parameter.empty:
            if a.get("default") is not None:
                _expect_type = {"string": str, "integer": int,
                                "number": float, "boolean": bool}[a["type"]]
                if p.default is not None and not isinstance(p.default,
                                                            _expect_type):
                    lines.append("CHECK FAIL: %s 参数 %s type=%s 与默认值 %r 类型不符"
                                 % (src, name, a["type"], p.default))
                if p.default is not None and a.get("default") is not None \
                        and p.default != a.get("default"):
                    lines.append("CHECK FAIL: %s 参数 %s 默认值 %r != 契约 %r"
                                 % (src, name, p.default, a.get("default")))


def run() -> tuple[bool, list[str]]:
    """执行全部一致性检查；返回 (是否通过, 明细行)。"""
    lines: list[str] = []
    errs = registry.validate_registry()
    for e in errs:
        lines.append("CHECK FAIL: " + e)
    if errs:
        return False, lines
    lines.append("registry: manifest 声明 %d 工具、%d 技能"
                 % (len(registry.tool_names()), len(registry.skill_dirs())))

    import handlers
    missing = [n for n in registry.tool_names() if n not in handlers.HANDLERS]
    orphan = [n for n in handlers.HANDLERS if n not in registry.tool_names()]
    for n in missing:
        lines.append("CHECK FAIL: manifest 声明 %s 但 handlers 无实现" % n)
    for n in orphan:
        lines.append("CHECK FAIL: handlers 实现 %s 但 manifest 未声明" % n)

    for spec in registry.tool_specs():
        fn = handlers.HANDLERS.get(spec["name"])
        if fn is not None:
            _check_signature(spec, fn, lines)

    for d, text in _skill_texts():
        _check_frontmatter(d, text, lines)

    texts = [t for _, t in _skill_texts()]
    for name in registry.tool_names():
        if not any(name in t for t in texts):
            lines.append("CHECK FAIL: 工具 %s 未被任何技能文档提及" % name)

    if not lines:
        lines.append("all consistency checks passed")
    return (not any(l.startswith("CHECK FAIL") for l in lines), lines)


def main() -> int:
    ok, lines = run()
    for l in lines:
        print(l)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
