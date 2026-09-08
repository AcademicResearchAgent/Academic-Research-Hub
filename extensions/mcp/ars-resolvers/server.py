"""Read-only bibliographic resolver APIs exposed through the official MCP SDK.

This is a thin FastMCP adapter over the resolver clients vendored from
Academic Research Skills v3.21.2 (`extensions/mcp/ars-resolvers/resolvers/`).
It exposes one verification tool per upstream index the existing
``paper-search`` service does not already cover: OpenAlex, Semantic Scholar,
arXiv and Chinese literature. Crossref and Europe PMC stay behind
``mcp__research_papers__*`` so the two MCP services do not overlap.

Each tool follows the ARS "lookup contract": given a citation-shaped input
(doi and/or title), it verifies existence and title agreement, and reports a
typed verdict rather than inventing a match. The vendored clients own the
network pacing, endpoint allow-list checks and typed degradation
(``*Unavailable``); this adapter only validates the input surface and normalizes
results into a ``{source, retrieved_at, verdict, record}`` envelope consistent
with ``paper-search/server.py``.

Run as a Hermes stdio MCP server via the extensions manifest (see
`docs/ARS-ADAPTATION-PLAN.md` §4).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Make the vendored package's sibling imports resolve (`from _text_similarity
# import ...`, `from contamination_signals import ...`). Inserted before the
# resolver modules are imported below.
_RESOLVERS_DIR = Path(__file__).resolve().parent / "resolvers"
if str(_RESOLVERS_DIR) not in sys.path:
    sys.path.insert(0, str(_RESOLVERS_DIR))

from _openalex_client import OpenAlexClient, OpenAlexUnavailable  # noqa: E402
from _semantic_scholar_client import SemanticScholarClient, SemanticScholarUnavailable  # noqa: E402
from _arxiv_client import ArxivClient, ArxivUnavailable  # noqa: E402
from _chinese_literature_client import ChineseLiteratureClient, ChineseLiteratureUnavailable  # noqa: E402

VERSION = "0.1.0"


def _envelope(source: str, **data: Any) -> dict[str, Any]:
    return {"source": source, "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "adapter_version": VERSION, **data}


def _require_text(value: Any, name: str, max_len: int = 1000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    text = value.strip()
    if len(text) > max_len:
        raise ValueError(f"{name} must not exceed {max_len} characters")
    return text


def _normalize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Copy only known citation fields, rejecting non-mapping input."""
    if not isinstance(entry, dict):
        raise ValueError("entry must be a mapping")
    allowed = {"title", "container_title", "doi", "arxiv_id", "volume",
               "issue", "pages", "year", "first_author_pinyin", "language"}
    return {k: v for k, v in entry.items() if k in allowed}


def openalex_verify(entry: dict[str, Any]) -> dict[str, Any]:
    """Verify one cited work against OpenAlex by DOI (title cross-check) then
    exact title search. Read-only; honors OpenAlex polite pacing. Returns
    {matched, record} with the full OpenAlex Work when verified."""
    entry = _normalize_entry(entry)
    doi = (entry.get("doi") or "").strip()
    title = _require_text(entry.get("title"), "title")
    client = OpenAlexClient()
    try:
        record = None
        if doi:
            record = client.doi_lookup_with_title_check(doi, title)
        if record is None:
            record = client.title_search(title, entry.get("year"))
        if record is None:
            return _envelope("OpenAlex", matched=False, record=None)
        return _envelope("OpenAlex", matched=True, record=record)
    except OpenAlexUnavailable as exc:
        return _envelope("OpenAlex", matched=False, degraded=True, error=str(exc))


def semantic_scholar_verify(entry: dict[str, Any]) -> dict[str, Any]:
    """Verify one cited work against Semantic Scholar by DOI then title
    fallback. Returns {matched, paperId}. Honors the 1 req/s unauthenticated
    floor and outage latch in the vendored client."""
    entry = _normalize_entry(entry)
    if not (str(entry.get("doi") or "").strip() or str(entry.get("title") or "").strip()):
        raise ValueError("entry must provide a doi or a title")
    client = SemanticScholarClient()
    try:
        result = client.lookup(entry)
        return _envelope("Semantic Scholar", **result)
    except SemanticScholarUnavailable as exc:
        return _envelope("Semantic Scholar", matched=False, degraded=True, error=str(exc))


def arxiv_verify(entry: dict[str, Any]) -> dict[str, Any]:
    """Verify one arXiv record by arXiv ID (title cross-check) then exact title
    search. Read-only; honors the arXiv ToU 3s pacing floor."""
    entry = _normalize_entry(entry)
    arxiv_id = (entry.get("arxiv_id") or "").strip()
    title = _require_text(entry.get("title"), "title")
    client = ArxivClient()
    try:
        record = None
        if arxiv_id:
            record = client.arxiv_id_lookup(arxiv_id, title)
        if record is None:
            record = client.title_search(title, entry.get("year"))
        if record is None:
            return _envelope("arXiv", matched=False, record=None)
        return _envelope("arXiv", matched=True, record=record)
    except ArxivUnavailable as exc:
        return _envelope("arXiv", matched=False, degraded=True, error=str(exc))


def chinese_literature_verify(entry: dict[str, Any]) -> dict[str, Any]:
    """Run the Chinese-literature waterfall resolver for one citation.

    Accepts a citation-shaped dict (title, container_title, doi, volume,
    issue, pages, year, first_author_pinyin, language). Returns the structured
    matched / unmatched / skipped result with a human-check checklist item;
    degradation raises an untyped boundary error the model must report.
    """
    entry = _normalize_entry(entry)
    title = str(entry.get("title") or "").strip()
    if title and len(title) > 1000:
        raise ValueError("title must not exceed 1000 characters")
    client = ChineseLiteratureClient()
    try:
        result = client.resolve(entry)
    except ChineseLiteratureUnavailable as exc:
        return _envelope("Chinese Literature", degraded=True, error=str(exc),
                         status="skipped", queried_by=None, reason_code=None)
    return _envelope("Chinese Literature", **result)


def create_server():
    from mcp.server.fastmcp import FastMCP
    server = FastMCP("ars_resolvers")
    server.tool()(openalex_verify)
    server.tool()(semantic_scholar_verify)
    server.tool()(arxiv_verify)
    server.tool()(chinese_literature_verify)
    return server


if __name__ == "__main__":
    create_server().run(transport="stdio")