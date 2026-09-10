"""Handlers for the research-frontier plugin.

They compute over records the caller already has. They never search databases, read
credentials or touch the network. Artifacts stay inside ``RESEARCH_FRONTIER_WORKSPACE``.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from .analysis import corpus, gap, hotspot, report


def _result(success: bool, **data) -> str:
    return json.dumps({"success": success, **data}, ensure_ascii=False)


def _workspace() -> Path:
    raw = os.environ.get("RESEARCH_FRONTIER_WORKSPACE")
    root = Path(raw).expanduser() if raw else Path(tempfile.gettempdir()) / "research-frontier"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _case_dir(case) -> Path:
    if case is not None and not isinstance(case, str):
        raise ValueError("case must be a string")
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", str(case or "").strip()).strip(".-")
    directory = _workspace() / "cases" / (name or "default")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _load(params: dict) -> tuple[list[dict], list[dict]]:
    return corpus.load_records(records=params.get("records"), records_path=params.get("records_path"))


def _int_param(params: dict, key: str, default: int) -> int:
    value = params.get(key, default)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _number_param(params: dict, key: str, default: float) -> float:
    value = params.get(key, default)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number")
    return float(value)


def corpus_profile(params: dict, **kwargs):
    try:
        records, dropped = _load(params)
        if not records:
            return _result(False, error="No record has a usable title.")
        fields = corpus.resolve_text_fields(params.get("text_fields"))
        return _result(True, **corpus.profile(records, dropped, fields))
    except (ValueError, OSError) as exc:
        return _result(False, error=str(exc))


def hotspot_analysis(params: dict, **kwargs):
    try:
        records, dropped = _load(params)
        if not records:
            return _result(False, error="No record has a usable title.")
        fields = corpus.resolve_text_fields(params.get("text_fields"))
        analysis = hotspot.analyze(
            records, fields,
            ngram_max=_int_param(params, "ngram_max", 2),
            min_count=_int_param(params, "min_count", 2),
            recent_years=_int_param(params, "recent_years", 3),
            top_k=_int_param(params, "top_k", 30),
        )
        case_dir = _case_dir(params.get("case"))
        json_path, markdown_path = case_dir / "hotspots.json", case_dir / "hotspots.md"
        _write_json(json_path, analysis)
        _write_text(markdown_path, hotspot.render_markdown(analysis))
        return _result(True, records=analysis["records"], dropped_count=len(dropped),
                       year_min=analysis["year_min"], year_max=analysis["year_max"],
                       term_count=analysis["term_count"], terms=analysis["terms"],
                       artifacts={"json": str(json_path), "markdown": str(markdown_path)},
                       methodology=analysis["methodology"], limitations=analysis["limitations"])
    except (ValueError, OSError) as exc:
        return _result(False, error=str(exc))


def gap_analysis(params: dict, **kwargs):
    try:
        records, dropped = _load(params)
        if not records:
            return _result(False, error="No record has a usable title.")
        fields = corpus.resolve_text_fields(params.get("text_fields"))
        analysis = gap.analyze(
            records, fields,
            params.get("domain_terms"), params.get("method_terms"),
            ngram_max=_int_param(params, "ngram_max", 2),
            min_support=_int_param(params, "min_support", 2),
            min_expected=_number_param(params, "min_expected", 1.5),
            top_k=_int_param(params, "top_k", 25),
        )
        case_dir = _case_dir(params.get("case"))
        json_path, markdown_path = case_dir / "gaps.json", case_dir / "gaps.md"
        _write_json(json_path, analysis)
        _write_text(markdown_path, gap.render_markdown(analysis))
        return _result(True, records=analysis["records"], dropped_count=len(dropped),
                       domain_terms=analysis["domain_terms"], method_terms=analysis["method_terms"],
                       candidate_gaps=analysis["candidate_gaps"], dense_pairs=analysis["dense_pairs"],
                       sparse_domains=analysis["sparse_domains"],
                       artifacts={"json": str(json_path), "markdown": str(markdown_path)},
                       methodology=analysis["methodology"], limitations=analysis["limitations"])
    except (ValueError, OSError) as exc:
        return _result(False, error=str(exc))


def report_build(params: dict, **kwargs):
    try:
        title = params.get("title")
        if title is not None and not isinstance(title, str):
            raise ValueError("title must be a string")
        analyses = report.load_analyses(params.get("analysis_paths"))
        result = report.build(analyses, title=title)
        path = _case_dir(params.get("case")) / "report.md"
        _write_text(path, result["markdown"])
        return _result(True, report_path=str(path), report=result["markdown"],
                       section_counts=result["section_counts"],
                       sources=result["sources"], limitations=report.limitations_text())
    except (ValueError, OSError) as exc:
        return _result(False, error=str(exc))
