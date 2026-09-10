"""Candidate research-gap detection from domain x method co-occurrence.

Under-observed cells with a sufficient expected count are reported as candidate gaps. This is
a bibliometric signal: it says the supplied corpus rarely combines two terms, not that the
combination is scientifically unexplored.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from . import text

ALGORITHM = "research-frontier/gap@0.1.0"
DEFAULT_TERMS_FILE = Path(__file__).resolve().parents[1] / "references" / "default_terms.json"
METHODOLOGY = (
    "Domain and method terms are matched against each record's title/keywords/abstract text. "
    "Observed pairs are the number of records containing both terms. Expected = (domain docs x "
    "method docs) / records. Residual is the Pearson residual (observed - expected) / sqrt(expected). "
    "Candidate gaps are cells with observed <= min_support and a negative residual at expected >= "
    "min_expected."
)
LIMITATIONS = (
    "Absence in a retrieved corpus is not evidence that a combination is unexplored; recall, "
    "language and database coverage all bias it. Term lists are supplied by the caller (or the "
    "bundled defaults) and define the whole result. No causal or novelty claim is made."
)


def default_terms() -> dict:
    payload = json.loads(DEFAULT_TERMS_FILE.read_text(encoding="utf-8"))
    return {"domain_terms": payload.get("domain_terms", []), "method_terms": payload.get("method_terms", [])}


def _normalize_terms(values, label: str) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, (list, tuple)) or not all(isinstance(item, str) for item in values):
        raise ValueError(f"{label} must be an array of strings")
    cleaned = []
    for item in values:
        term = text.normalize_term(item)
        if term and term not in cleaned:
            cleaned.append(term)
    return cleaned


def analyze(records, text_fields, domain_terms, method_terms, *, ngram_max=2,
            min_support=2, min_expected=1.5, top_k=25) -> dict:
    if not records:
        raise ValueError("No usable record to analyze.")
    domains = _normalize_terms(domain_terms, "domain_terms")
    methods = _normalize_terms(method_terms, "method_terms")
    if not domains and not methods:
        fallback = default_terms()
        domains = _normalize_terms(fallback["domain_terms"], "domain_terms")
        methods = _normalize_terms(fallback["method_terms"], "method_terms")
    if not domains:
        raise ValueError("domain_terms is required (no default could be applied)")
    if not methods:
        raise ValueError("method_terms is required (no default could be applied)")
    overlap = sorted(set(domains) & set(methods))
    if overlap:
        raise ValueError("a term cannot be both a domain and a method term: " + ", ".join(overlap))
    if min_support < 0:
        raise ValueError("min_support must not be negative")
    if min_expected < 0:
        raise ValueError("min_expected must not be negative")
    if top_k < 1:
        raise ValueError("top_k must be at least 1")
    if not 1 <= ngram_max <= 4:
        raise ValueError("ngram_max must be between 1 and 4")

    texts, doc_terms = [], []
    for record in records:
        content = text.record_text(record, text_fields)
        texts.append(content)
        doc_terms.append(text.record_terms(content, ngram_max))

    total = len(records)
    presence = {
        term: [text.term_is_present(term, doc_terms[index], texts[index]) for index in range(total)]
        for term in domains + methods
    }
    frame = pd.DataFrame(presence)
    counts = frame.sum(axis=0)
    co_occurrence = frame.astype(int).T.dot(frame.astype(int))

    gaps, dense = [], []
    for domain in domains:
        for method in methods:
            observed = int(co_occurrence.at[domain, method])
            expected = float(counts[domain]) * float(counts[method]) / total
            if expected < min_expected:
                continue
            residual = (observed - expected) / math.sqrt(expected)
            row = {"domain": domain, "method": method, "observed": observed,
                   "expected": round(expected, 2), "residual": round(residual, 3)}
            if observed <= min_support and residual < 0:
                gaps.append(row)
            elif residual > 0:
                dense.append(row)

    gaps.sort(key=lambda row: (row["residual"], row["domain"], row["method"]))
    dense.sort(key=lambda row: (-row["residual"], row["domain"], row["method"]))
    sparse = sorted(({"domain": domain, "documents": int(counts[domain])} for domain in domains),
                    key=lambda row: (row["documents"], row["domain"]))[:5]

    return {
        "algorithm": ALGORITHM,
        "records": total,
        "parameters": {"min_support": min_support, "min_expected": min_expected, "top_k": top_k,
                       "ngram_max": ngram_max, "text_fields": list(text_fields)},
        "domain_terms": domains,
        "method_terms": methods,
        "candidate_gaps": gaps[:top_k],
        "dense_pairs": dense[:top_k],
        "sparse_domains": sparse,
        "methodology": METHODOLOGY,
        "limitations": LIMITATIONS,
    }


def render_markdown(analysis: dict) -> str:
    lines = [
        "# 候选研究空白 / Candidate research gaps",
        "",
        f"- 记录数 / records: {analysis['records']}",
        f"- 领域词 / domain terms: {len(analysis['domain_terms'])}，方法词 / method terms: {len(analysis['method_terms'])}",
        "",
        "## 低共现候选 / Under-observed pairs",
        "",
        "| 领域 domain | 方法 method | 观测 observed | 期望 expected | 残差 residual |",
        "| --- | --- | --- | --- | --- |",
    ]
    if analysis["candidate_gaps"]:
        for row in analysis["candidate_gaps"]:
            lines.append("| {domain} | {method} | {observed} | {expected} | {residual} |".format(**row))
    else:
        lines.append("| - | - | - | - | - |")
    lines += ["", "## 高共现组合 / Dense pairs", "",
              "| 领域 domain | 方法 method | 观测 observed | 期望 expected | 残差 residual |",
              "| --- | --- | --- | --- | --- |"]
    for row in analysis["dense_pairs"]:
        lines.append("| {domain} | {method} | {observed} | {expected} | {residual} |".format(**row))
    lines += ["", "## 低文献量领域 / Sparse domains", "",
              "| 领域 domain | 文献数 docs |", "| --- | --- |"]
    for row in analysis["sparse_domains"]:
        lines.append("| {domain} | {documents} |".format(**row))
    lines += ["", "## 方法 / Methodology", "", analysis["methodology"],
              "", "## 局限 / Limitations", "", analysis["limitations"], ""]
    return "\n".join(lines)
