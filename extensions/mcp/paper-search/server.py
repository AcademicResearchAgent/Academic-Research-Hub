"""Read-only scholarly APIs exposed through the official MCP Python SDK."""
import json
import re
import threading
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import quote
from xml.etree import ElementTree as ET

VERSION = "1.0.0"
EP = "https://www.ebi.ac.uk/europepmc/webservices/rest"
CR = "https://api.crossref.org/works"
MAX_BYTES = 5_000_000
_lock = threading.Lock()
_last_request = 0.0


class APIError(RuntimeError):
    pass


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain(value):
    parser = PlainText()
    parser.feed(str(value or ""))
    return " ".join(" ".join(parser.parts).split())


def request(url, params=None):
    """Fixed callers only; no arbitrary URL tool. Bound time, size and request rate."""
    import httpx
    global _last_request
    with _lock:
        time.sleep(max(0, 1 - (time.monotonic() - _last_request)))
        _last_request = time.monotonic()
    try:
        with httpx.Client(timeout=20, follow_redirects=False, trust_env=False,
                          headers={"User-Agent": "Academic-Research-Hub/" + VERSION}) as client:
            with client.stream("GET", url, params=params) as response:
                if response.status_code != 200:
                    raise APIError(f"Upstream HTTP {response.status_code}; retry later for 429/5xx. Full text may be unavailable for 404/403.")
                parts, size = [], 0
                for part in response.iter_bytes():
                    size += len(part)
                    if size > MAX_BYTES:
                        raise APIError("Upstream response exceeds 5 MB limit.")
                    parts.append(part)
                return b"".join(parts)
    except httpx.HTTPError as exc:
        raise APIError("Upstream network or timeout error; no results retrieved.") from exc


def bounds(query, limit):
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 500:
        raise ValueError("query must contain 1–500 characters")
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError("limit must be an integer from 1 to 10")


def doi_value(doi):
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi.strip(), flags=re.I)
    if not re.fullmatch(r"10\.\d{4,9}/\S{1,200}", doi):
        raise ValueError("Provide a DOI beginning with 10., or its doi.org URL")
    return doi


def envelope(source, **data):
    return {"source": source, "retrieved_at": datetime.now(timezone.utc).isoformat(), **data}


def crossref_record(item):
    date = item.get("published", {}).get("date-parts", [[]])
    doi = item.get("DOI", "")
    abstract = plain(item.get("abstract"))
    return {"title": plain((item.get("title") or [""])[0]),
            "authors": [plain(a.get("name") or " ".join(filter(None, [a.get("given"), a.get("family")])))
                        for a in item.get("author", [])],
            "year": date[0][0] if date and date[0] else None,
            "journal": plain((item.get("container-title") or [""])[0]),
            "doi": doi, "url": "https://doi.org/" + quote(doi, safe="/") if doi else None,
            "abstract": abstract[:6000], "abstract_truncated": len(abstract) > 6000,
            "evidence_level": "abstract" if abstract else "metadata",
            "licenses": [x.get("URL") for x in item.get("license", []) if x.get("URL")]}


def crossref_search(query: str, limit: int = 5) -> dict:
    """Search Crossref scholarly metadata across disciplines. Does not fetch full text."""
    bounds(query, limit)
    data = json.loads(request(CR, {"query.bibliographic": query, "rows": limit}))["message"]
    return envelope("Crossref", query=query, total=data.get("total-results"),
                    records=[crossref_record(x) for x in data.get("items", [])])


def crossref_lookup(doi: str) -> dict:
    """Resolve a known Crossref DOI to deposited metadata; use to check a citation."""
    doi = doi_value(doi)
    data = json.loads(request(CR + "/" + quote(doi, safe="")))["message"]
    return envelope("Crossref", record=crossref_record(data))


def europepmc_search(query: str, limit: int = 5) -> dict:
    """Search Europe PMC life-science literature, including PubMed records and abstracts.

    Supports Europe PMC syntax, e.g. 'CRISPR OPEN_ACCESS:Y' or 'EXT_ID:30049270'.
    Returned is_open_access is an upstream flag, not proof full text was retrieved.
    """
    bounds(query, limit)
    data = json.loads(request(EP + "/search", {"query": query, "format": "json",
                                              "resultType": "core", "pageSize": limit}))
    records = []
    for item in data.get("resultList", {}).get("result", []):
        abstract = plain(item.get("abstractText"))
        records.append({"title": plain(item.get("title")), "authors": item.get("authorString", ""),
                        "year": item.get("pubYear"), "doi": item.get("doi"), "pmcid": item.get("pmcid"),
                        "id": item.get("id"), "source_collection": item.get("source"),
                        "url": "https://europepmc.org/article/" + quote(str(item.get("source", "")), safe="")
                               + "/" + quote(str(item.get("id", "")), safe=""),
                        "abstract": abstract[:6000], "abstract_truncated": len(abstract) > 6000,
                        "is_open_access": item.get("isOpenAccess") == "Y",
                        "evidence_level": "abstract" if abstract else "metadata"})
    return envelope("Europe PMC", query=query, total=data.get("hitCount"), records=records)


def extract_fulltext(raw, pmcid, offset, max_chars):
    if b"<!ENTITY" in raw.upper():
        raise APIError("XML entity declarations are not supported.")
    root = ET.fromstring(raw)
    body = root.find(".//body")
    if body is None:
        raise APIError("Response has no article body; full text was not retrieved.")
    paragraphs = [" ".join("".join(node.itertext()).split()) for node in body.iter()
                  if node.tag in {"title", "p"}]
    text = "\n\n".join(filter(None, paragraphs))
    if not text:
        raise APIError("Article body contains no extractable paragraphs.")
    end = min(offset + max_chars, len(text))
    license_node = root.find(".//license")
    license_text = " ".join("".join(license_node.itertext()).split()) if license_node is not None else ""
    return envelope("Europe PMC", pmcid=pmcid, url=f"https://europepmc.org/articles/{pmcid}",
                    license=license_text,
                    evidence_level="fulltext_excerpt", text=text[offset:end], total_chars=len(text),
                    offset=offset, next_offset=end if end < len(text) else None,
                    truncated=offset > 0 or end < len(text),
                    note="Extracted body paragraphs; figures, tables and supplements are not fully represented.")


def europepmc_fulltext(pmcid: str, offset: int = 0, max_chars: int = 12000) -> dict:
    """Read a paginated body excerpt from Europe PMC's open-access fullTextXML API.

    Requires a PMCID such as PMC7098031. Follow next_offset to read further.
    Does not bypass publisher access controls or retrieve arbitrary PDFs.
    """
    if not re.fullmatch(r"PMC[0-9]{1,12}", pmcid):
        raise ValueError("pmcid must match PMC followed by digits")
    if type(offset) is not int or not 0 <= offset <= MAX_BYTES:
        raise ValueError("offset must be between 0 and 5000000")
    if type(max_chars) is not int or not 1000 <= max_chars <= 20000:
        raise ValueError("max_chars must be between 1000 and 20000")
    return extract_fulltext(request(EP + "/" + pmcid + "/fullTextXML"), pmcid, offset, max_chars)


def create_server():
    from mcp.server.fastmcp import FastMCP
    server = FastMCP("research_papers")
    for tool in (crossref_search, crossref_lookup, europepmc_search, europepmc_fulltext):
        server.tool()(tool)
    return server


if __name__ == "__main__":
    create_server().run(transport="stdio")
