"""Vendored resolver clients from Academic Research Skills v3.21.2.

Each module is copied byte-for-byte from the upstream suite's `scripts/` and
renamed with an underscore prefix so the package-level names stay private. The
client modules use a "sibling-first" import for `_text_similarity`; adding this
package directory to `sys.path` (done in `server.py` before importing them)
lets that import resolve without relying on the upstream `scripts.` namespace
package fallback.

Upstream files:
    _text_similarity.py          <- scripts/_text_similarity.py
    _openalex_client.py          <- scripts/openalex_client.py
    _semantic_scholar_client.py  <- scripts/semantic_scholar_client.py
    _arxiv_client.py             <- scripts/arxiv_client.py
    _chinese_literature_client.py<- scripts/chinese_literature_client.py

These are partial ports. The upstream verification_gate, retraction_status and
temporal_integrity_audit deterministic checkers are OUT of scope for this
increment (see docs/ARS-ADAPTATION-PLAN.md §3, the plugin increment).

The sibling-first import path is wired here so the package works as a whole:
importing a resolver directly also imports `_text_similarity` from the same
directory.
"""
from __future__ import annotations

__all__ = [
    "_text_similarity",
    "_openalex_client",
    "_semantic_scholar_client",
    "_arxiv_client",
    "_chinese_literature_client",
]