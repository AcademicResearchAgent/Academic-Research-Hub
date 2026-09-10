"""Assemble research-frontier analysis artifacts into one Markdown report."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ALGORITHM = "research-frontier/report@0.1.0"
LIMITATIONS_FILE = Path(__file__).resolve().parents[1] / "references" / "limitations.md"
_FALLBACK_LIMITATIONS = (
    "All figures are bibliometric proxies over one retrieved record set. They do not measure "
    "scientific importance, novelty or correctness, and they never replace expert judgement."
)


def limitations_text() -> str:
    if LIMITATIONS_FILE.is_file():
        return LIMITATIONS_FILE.read_text(encoding="utf-8").strip()
    return _FALLBACK_LIMITATIONS


def _classify(payload: dict) -> str:
    if "candidate_gaps" in payload:
        return "gap"
    if "terms" in payload:
        return "hotspot"
    if "record_count" in payload:
        return "profile"
    return "unknown"


def load_analyses(analysis_paths) -> list[dict]:
    if not isinstance(analysis_paths, (list, tuple)) or not analysis_paths:
        raise ValueError("analysis_paths must be a non-empty array of JSON artifact paths")
    analyses = []
    for raw_path in analysis_paths:
        path = Path(str(raw_path)).expanduser()
        if not path.is_file():
            raise ValueError(f"analysis artifact not found: {raw_path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"analysis artifact is not readable JSON: {raw_path} ({exc})") from None
        if not isinstance(payload, dict):
            raise ValueError(f"analysis artifact is not a JSON object: {raw_path}")
        payload = dict(payload)
        payload["_source"] = str(path.resolve())
        payload["_kind"] = _classify(payload)
        analyses.append(payload)
    return analyses


def build(analyses: list[dict], *, title=None) -> dict:
    if not analyses:
        raise ValueError("at least one analysis artifact is required")
    heading = title or "研究前沿与空白分析 / Research frontier and gap analysis"
    lines = [f"# {heading}", "",
             f"生成时间 / generated: {datetime.now(timezone.utc).isoformat()}",
             f"输入产物 / inputs: {len(analyses)}", ""]
    counts = {"profile": 0, "hotspot": 0, "gap": 0, "unknown": 0}
    for analysis in analyses:
        kind = analysis["_kind"]
        counts[kind] = counts.get(kind, 0) + 1
        lines += [f"## {analysis['_source']}", ""]
        if kind == "hotspot":
            lines += _hotspot_section(analysis)
        elif kind == "gap":
            lines += _gap_section(analysis)
        elif kind == "profile":
            lines += _profile_section(analysis)
        else:
            lines += ["- 未识别的产物类型 / unrecognised artifact type.", ""]
    lines += ["## 方法 / Methodology", "",
              "- Terms are document-frequency surface forms; the recent window is anchored on the newest year in the corpus.",
              "- Candidate gaps are under-observed domain x method cells, not confirmed research gaps.",
              "", "## 局限 / Limitations", "", limitations_text(), ""]
    return {"markdown": "\n".join(lines), "section_counts": counts,
            "algorithm": ALGORITHM, "sources": [analysis["_source"] for analysis in analyses]}


def _hotspot_section(analysis: dict) -> list[str]:
    lines = [f"- 记录数 / records: {analysis.get('records')}",
             f"- 年份范围 / years: {analysis.get('year_min')}–{analysis.get('year_max')}", "",
             "| 词 term | 文献数 docs | 占比 share | 突现比 burst |", "| --- | --- | --- | --- |"]
    for term in (analysis.get("terms") or [])[:15]:
        burst = "-" if term.get("burst_ratio") is None else term["burst_ratio"]
        lines.append(f"| {term.get('term')} | {term.get('documents')} | {term.get('share')} | {burst} |")
    lines.append("")
    return lines


def _gap_section(analysis: dict) -> list[str]:
    lines = [f"- 记录数 / records: {analysis.get('records')}", "",
             "| 领域 domain | 方法 method | 观测 observed | 期望 expected | 残差 residual |",
             "| --- | --- | --- | --- | --- |"]
    gaps = analysis.get("candidate_gaps") or []
    if gaps:
        for row in gaps[:15]:
            lines.append("| {domain} | {method} | {observed} | {expected} | {residual} |".format(**row))
    else:
        lines.append("| - | - | - | - | - |")
    lines.append("")
    return lines


def _profile_section(analysis: dict) -> list[str]:
    lines = [f"- 记录数 / records: {analysis.get('record_count')}",
             f"- 丢弃记录 / dropped: {analysis.get('dropped_count')}",
             f"- 年份范围 / years: {analysis.get('year_min')}–{analysis.get('year_max')}",
             f"- 缺失字段 / missing: {analysis.get('missing')}"]
    for warning in analysis.get("warnings") or []:
        lines.append(f"- 注意 / warning: {warning}")
    lines.append("")
    return lines
