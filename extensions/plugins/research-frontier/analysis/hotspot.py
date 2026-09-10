"""Hotspot, trend and burst detection over normalized records.

All figures are document frequencies within the supplied record set. The recent window is
anchored on the newest publication year present in the corpus, not the wall clock, so a
fixed input always produces a fixed output.
"""
from __future__ import annotations

import math
from collections import Counter

import numpy as np
import pandas as pd

from . import text

ALGORITHM = "research-frontier/hotspot@0.1.0"
METHODOLOGY = (
    "Document frequencies over the supplied records. Terms: ASCII words >=2 chars plus word "
    "n-grams built before stopword removal; CJK runs become character bigrams. The recent "
    "window is the newest N publication years in this corpus. burst_ratio compares per-document "
    "rate in the recent window against the earlier window."
)
LIMITATIONS = (
    "Bibliometric proxy only: it measures what this record set contains, not scientific "
    "importance, novelty or correctness. A small or biased corpus yields unstable terms. "
    "Terms are surface forms, so synonyms and abbreviations are counted separately. Records "
    "without a usable year are excluded from trend and burst figures."
)


def _document_terms(records, text_fields, ngram_max):
    texts, terms = [], []
    for record in records:
        content = text.record_text(record, text_fields)
        texts.append(content)
        terms.append(text.record_terms(content, ngram_max))
    return texts, terms


def analyze(records, text_fields, *, ngram_max=2, min_count=2, recent_years=3, top_k=30) -> dict:
    if not records:
        raise ValueError("No usable record to analyze.")
    if not 1 <= ngram_max <= 4:
        raise ValueError("ngram_max must be between 1 and 4")
    if min_count < 1:
        raise ValueError("min_count must be at least 1")
    if not 1 <= recent_years <= 50:
        raise ValueError("recent_years must be between 1 and 50")
    if top_k < 1:
        raise ValueError("top_k must be at least 1")

    _, doc_terms = _document_terms(records, text_fields, ngram_max)
    total = len(records)
    years = [record["year"] for record in records if record["year"]]
    max_year = max(years) if years else None
    docs_per_year = Counter(years)

    term_documents: Counter = Counter()
    term_years: dict[str, Counter] = {}
    for record, terms in zip(records, doc_terms):
        for term in terms:
            term_documents[term] += 1
            if record["year"]:
                term_years.setdefault(term, Counter())[record["year"]] += 1

    recent_docs = prior_docs = 0
    if max_year is not None:
        recent_docs = sum(count for year, count in docs_per_year.items() if year > max_year - recent_years)
        prior_docs = sum(count for year, count in docs_per_year.items() if year <= max_year - recent_years)

    rows = []
    for term, count in term_documents.items():
        if count < min_count:
            continue
        yearly = term_years.get(term, Counter())
        series = pd.Series(dict(yearly), dtype="float64").sort_index()
        slope = None
        if len(series) >= 3:
            slope = float(np.polyfit(series.index.to_numpy(dtype=float), series.to_numpy(dtype=float), 1)[0])

        recent_hits = sum(value for year, value in yearly.items() if max_year and year > max_year - recent_years)
        prior_hits = sum(value for year, value in yearly.items() if max_year and year <= max_year - recent_years)
        recent_rate = recent_hits / recent_docs if recent_docs else 0.0
        prior_rate = prior_hits / prior_docs if prior_docs else 0.0
        if max_year is None or prior_docs == 0:
            burst_ratio, note = None, "no earlier window to compare"
        elif prior_hits == 0:
            burst_ratio, note = None, "absent before the recent window"
        else:
            burst_ratio, note = round(recent_rate / prior_rate, 3), None

        rows.append({
            "term": term,
            "documents": int(count),
            "share": round(count / total, 4),
            "idf": round(math.log(total / count), 4),
            "trend_slope": round(slope, 4) if slope is not None else None,
            "recent_documents": int(recent_hits),
            "recent_rate": round(recent_rate, 4),
            "prior_rate": round(prior_rate, 4),
            "burst_ratio": burst_ratio,
            "note": note,
            "years": dict(sorted(yearly.items())),
        })

    frame = pd.DataFrame(rows).sort_values(["documents", "term"], ascending=[False, True]).head(top_k)
    terms = []
    for _, row in frame.iterrows():
        terms.append({
            "term": str(row["term"]),
            "documents": int(row["documents"]),
            "share": float(row["share"]),
            "idf": float(row["idf"]),
            "trend_slope": None if pd.isna(row["trend_slope"]) else float(row["trend_slope"]),
            "recent_documents": int(row["recent_documents"]),
            "recent_rate": float(row["recent_rate"]),
            "prior_rate": float(row["prior_rate"]),
            "burst_ratio": None if pd.isna(row["burst_ratio"]) else float(row["burst_ratio"]),
            "note": None if row["note"] is None else str(row["note"]),
            "years": {int(year): int(value) for year, value in row["years"].items()},
        })

    return {
        "algorithm": ALGORITHM,
        "records": total,
        "year_min": min(years) if years else None,
        "year_max": max_year,
        "recent_window": {"years": recent_years, "from_year": (max_year - recent_years + 1) if max_year else None,
                          "documents": recent_docs, "prior_documents": prior_docs},
        "parameters": {"ngram_max": ngram_max, "min_count": min_count, "top_k": top_k, "text_fields": list(text_fields)},
        "term_count": len(rows),
        "terms": terms,
        "methodology": METHODOLOGY,
        "limitations": LIMITATIONS,
    }


def render_markdown(analysis: dict) -> str:
    lines = [
        "# 热点与趋势 / Hotspots and trends",
        "",
        f"- 记录数 / records: {analysis['records']}",
        f"- 年份范围 / years: {analysis['year_min']}–{analysis['year_max']}",
        f"- 近期窗口 / recent window: {analysis['recent_window']['years']} 年，起始 {analysis['recent_window']['from_year']}",
        "",
        "| 词 term | 文献数 docs | 占比 share | 趋势斜率 slope | 近期速率 recent | 基线速率 prior | 突现比 burst |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for term in analysis["terms"]:
        lines.append("| {term} | {documents} | {share} | {trend_slope} | {recent_rate} | {prior_rate} | {burst_ratio} |".format(
            term=term["term"], documents=term["documents"], share=term["share"],
            trend_slope="-" if term["trend_slope"] is None else term["trend_slope"],
            recent_rate=term["recent_rate"], prior_rate=term["prior_rate"],
            burst_ratio="-" if term["burst_ratio"] is None else term["burst_ratio"]))
    lines += ["", "## 方法 / Methodology", "", analysis["methodology"], "", "## 局限 / Limitations", "", analysis["limitations"], ""]
    return "\n".join(lines)
