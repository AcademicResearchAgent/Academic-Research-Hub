"""Compatibility shim for the vendored Semantic Scholar client.

`_semantic_scholar_client.py` (upstream `scripts/semantic_scholar_client.py`)
imports `SemanticScholarUnavailable` from `contamination_signals`, the module
that owns the v3.7.3 contamination-signals computation in the upstream suite.
That computation is out of scope for this MCP increment; only the small
exception class the client raises is needed here, so this shim exposes just
that name. The parent directory is placed on ``sys.path`` by ``server.py``
before the resolvers are imported, which lets the vendored client's
sibling-first ``from contamination_signals import ...`` resolve.

This is a module for the vendored client only; nothing else in this package
imports it.
"""


class SemanticScholarUnavailable(Exception):
    """Semantic Scholar API degraded -- caller MUST omit the S2 signal."""