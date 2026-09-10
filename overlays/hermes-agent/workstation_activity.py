"""Public, bounded tool receipts. No model calls; never forward raw args/output."""
import json
import re
import time
from urllib.parse import urlsplit, urlunsplit


def clean(value, limit=320):
    if not isinstance(value, (str, int, float)):
        return ""
    value = re.sub(r"(?i)(?:sk-[\w-]+|bearer\s+\S+|(?:api[_-]?key|token|password|secret)\s*[:=]\s*[^\s&,;]+)", "[已隐藏凭据]", str(value))
    value = re.sub(r"https?://\S+", lambda m: safe_url(m[0]), value)
    return " ".join(value.split())[:limit]


def safe_url(value):
    try:
        p = urlsplit(str(value))
        if p.scheme not in {"http", "https"} or not p.hostname:
            return ""
        # Strip userinfo, query and fragment, including signed download credentials.
        path = re.sub(r"(?i)sk-[\w-]+", "[redacted]", p.path)
        return urlunsplit((p.scheme, p.hostname, path, "", ""))[:1000]
    except ValueError:
        return ""


def decode(value, depth=0):
    if depth > 6:
        return {}
    if isinstance(value, str):
        if len(value) > 2_000_000:
            return {}
        try:
            return decode(json.loads(value), depth + 1)
        except (ValueError, TypeError):
            return {"error": True} if re.match(r"\s*(error|failed|exception|blocked)\b", value, re.I) else {}
    if isinstance(value, list):
        for item in value[:10]:
            if isinstance(item, dict) and item.get('type') == 'text':
                return decode(item.get('text'), depth + 1)
        return {}
    if not isinstance(value, dict):
        return {}
    if value.get("isError") or value.get("error") or value.get("success") is False:
        return {"error": True}
    if 'result' in value and isinstance(value['result'], (dict, list, str)):
        return decode(value['result'], depth + 1)
    if isinstance(value.get("structuredContent"), dict):
        return decode(value["structuredContent"], depth + 1)
    if isinstance(value.get("content"), list):
        for item in value["content"][:10]:
            if isinstance(item, dict) and item.get("type") == "text":
                result = decode(item.get("text"), depth + 1)
                if result:
                    return result
    return value


def start_activity(tool, args):
    args = decode(args)
    name = tool.rsplit("__", 1)[-1]
    source = "Crossref" if name.startswith("crossref_") else "Europe PMC" if name.startswith("europepmc_") else ""
    title, detail = clean(tool, 100), ""
    if name in {"crossref_search", "europepmc_search", "web_search"}:
        title = "检索 · " + (source or "网页搜索")
        detail = "检索式：" + clean(args.get("query"))
    elif name == "crossref_lookup":
        title, detail = "核对文献 · Crossref", "DOI：" + clean(args.get("doi"))
    elif name == "europepmc_fulltext":
        title, detail = "读取论文正文 · Europe PMC", clean(args.get("pmcid")) + " · 起始字符 " + clean(args.get("offset", 0))
    elif name in {"web_extract", "browser_navigate"}:
        title = "提取网页／PDF 内容" if name == "web_extract" else "浏览网页"
        urls = args.get("urls", [args.get("url", "")])
        detail = "；".join(filter(None, (safe_url(u) for u in urls[:5]))) if isinstance(urls, list) else ""
    elif name in {"skill_view", "skill_manage", "skills_list", "tool_describe", "tool_search"}:
        title = {"skill_view": "加载研究方法", "skill_manage": "管理研究方法", "skills_list": "查看研究方法", "tool_describe": "查看工具用法", "tool_search": "查找工具"}[name]
        names = args.get("names", args.get("name", args.get("query", "")))
        detail = clean(", ".join(names) if isinstance(names, list) and all(isinstance(x, str) for x in names) else names)
    elif name in {"read_file", "write_file", "patch"}:
        title = {"read_file": "读取文件", "write_file": "写入文件", "patch": "修改文件"}[name]
        detail = clean(str(args.get("path", "")).replace("\\", "/").rsplit("/", 1)[-1])
    elif name == "terminal":
        title = "执行终端命令"
        # Program only: shell arguments/output can contain user secrets.
        match = re.match(r"\s*([a-zA-Z][\w.-]{0,40})(?:\s|$)", str(args.get("command", "")))
        detail = "程序：" + match[1] if match else "命令已提交"
    elif name.startswith("browser_"):
        title = "浏览器操作 · " + {"browser_snapshot": "读取页面", "browser_click": "点击元素", "browser_scroll": "滚动页面", "browser_type": "填写页面", "browser_back": "返回页面"}.get(name, clean(name))
    elif name in {"delegate_task", "todo"}:
        title = "分派研究子任务" if name == "delegate_task" else "更新任务计划"
    return {"title": title, "detail": detail, "state": "running", "source": source}


def finish_activity(activity, tool, result, elapsed):
    out = {**activity, "state": "completed", "elapsed": round(max(0, elapsed), 1), "summary": "执行结束", "items": []}
    data = decode(result)
    if data.get("error") or data.get("exit_code") not in (None, 0):
        return {**out, "state": "failed", "summary": "工具返回错误，未取得有效结果"}
    records = data.get("records")
    if isinstance(data.get("record"), dict):
        records = [data["record"]]
    if tool == "web_search":
        records = data.get("data", {}).get("web") if isinstance(data.get("data"), dict) else None
    if isinstance(records, list):
        out["summary"] = f"返回 {len(records)} 条结果" + ("（未命中）" if not records else "")
        out["items"] = [{"title": clean(r.get("title")), "url": safe_url(r.get("url", "")),
                         "note": " · ".join(filter(None, [clean(r.get("year")), clean(r.get("doi")),
                             {"metadata": "题录", "abstract": "含摘要"}.get(r.get("evidence_level"), "网页结果")]))}
                        for r in records[:10] if isinstance(r, dict)]
        if len(records) > 10:
            out["summary"] += " · 展示前 10 条"
    elif data.get("evidence_level") == "fulltext_excerpt" and isinstance(data.get("text"), str):
        chars = len(data["text"])
        out["summary"] = f"已读取正文 {chars} 字符 · 起始 {clean(data.get('offset', 0))} · 正文共 {clean(data.get('total_chars'))} 字符"
        out["items"] = [{"title": clean(data.get("pmcid")), "url": safe_url(data.get("url", "")), "note": "正文节选；不代表已阅读整篇论文、图表及补充材料"}]
    elif tool == "web_extract" and isinstance(data.get("results"), list):
        rows = data["results"]
        good = 0
        for row in rows[:10]:
            content = row.get("content") or row.get("raw_content") or ""
            valid = not row.get("error") and isinstance(content, str) and bool(content)
            good += int(valid)
            out["items"].append({"title": clean(row.get("title")) or safe_url(row.get("url", "")),
                                 "url": safe_url(row.get("url", "")),
                                 "note": f"已提取 {len(content)} 字符（工具返回内容，可能截断）" if valid else "读取失败／无可读内容"})
        out["summary"] = f"读取 {good}/{len(rows)} 个页面；网页提取不等同于已取得论文全文"
        if good != len(rows):
            out["state"] = "partial" if good else "failed"
    elif not data:
        out["summary"] = "调用已返回；此工具未提供可展示的结构化结果"
    return out


class ActivityTracker:
    def __init__(self):
        self.calls = {}

    def start(self, call_id, tool, args):
        activity = start_activity(tool, args)
        self.calls[call_id] = (activity, time.monotonic())
        return {"tool": tool, "toolCallId": call_id, "status": "running", "activity": activity}

    def complete(self, call_id, tool, result):
        activity, started = self.calls.pop(call_id)
        receipt = finish_activity(activity, tool, result, time.monotonic() - started)
        return {"tool": tool, "toolCallId": call_id, "status": "completed", "activity": receipt}
