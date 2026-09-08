"""Hermes plugin using only the public register(ctx) interface."""
import json
import re
from urllib.parse import quote, urlsplit


def handle_citation(params, **kwargs):
    del kwargs
    def clean(value):
        return " ".join(str(value or "").split())

    title = clean(params.get("title"))
    if not title:
        return json.dumps({"success": False, "error": "A retrieved title is required."})
    authors = params.get("authors") or []
    if not isinstance(authors, list) or any(not isinstance(a, str) for a in authors):
        return json.dumps({"success": False, "error": "authors must be a list of strings"})
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", clean(params.get("doi")), flags=re.I)
    if doi and not re.fullmatch(r"10\.\d{4,9}/\S{1,200}", doi):
        return json.dumps({"success": False, "error": "Invalid DOI syntax; do not guess a DOI."})
    url = clean(params.get("url"))
    try:
        parsed = urlsplit(url)
    except ValueError:
        return json.dumps({"success": False, "error": "Invalid source URL"})
    if url and (parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password):
        return json.dumps({"success": False, "error": "url must be an HTTP(S) source link without credentials"})
    year = clean(params.get("year"))
    if year and not re.fullmatch(r"[0-9]{4}", year):
        return json.dumps({"success": False, "error": "year must be four digits or omitted"})
    parts = ["; ".join(clean(a) for a in authors if clean(a)), title, clean(params.get("journal")), year]
    link = "https://doi.org/" + quote(doi, safe="/") if doi else url
    result = ". ".join(p for p in parts if p)
    return json.dumps({"success": True, "reference": result + (". " + link if link else ""),
                       "source_url": link or None, "verified": False,
                       "note": "Plain reference, not CSL/APA/GB/T compliance. Metadata must be verified at its source."}, ensure_ascii=False)


def register(ctx):
    ctx.register_tool(
        name="research_citation", toolset="research_citations", handler=handle_citation,
        schema={"name": "research_citation",
                "description": "Format retrieved paper metadata into a plain citation with a DOI/source link. Does not verify facts or invent missing fields.",
                "parameters": {"type": "object", "properties": {
                    "title": {"type": "string"},
                    "authors": {"type": "array", "items": {"type": "string"}},
                    "year": {"type": "string", "description": "Four digits, or omit when unknown"},
                    "journal": {"type": "string"}, "doi": {"type": "string"}, "url": {"type": "string"}
                }, "required": ["title"], "additionalProperties": False}})
