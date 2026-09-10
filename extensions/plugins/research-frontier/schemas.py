"""JSON schemas exposed to Hermes."""

_RECORD_INPUT = {
    "records_path": {"type": "string", "description": "Path to a JSON or JSONL file of retrieved records"},
    "records": {"type": "array", "items": {"type": "object"},
                "description": "Inline records, for small sets only"},
    "text_fields": {"type": "array", "items": {"type": "string", "enum": ["title", "abstract", "keywords", "venue"]},
                    "description": "Record fields counted as text; defaults to title + keywords"},
}
_RECORD_SOURCE = {"oneOf": [{"required": ["records_path"]}, {"required": ["records"]}]}

PROFILE = {
    "name": "frontier_corpus_profile",
    "description": "Validate and summarise an already-retrieved literature record set (year range, field coverage, duplicate DOIs) before any analysis. Read-only; never searches the web.",
    "parameters": {"type": "object", "properties": dict(_RECORD_INPUT), **_RECORD_SOURCE},
}

HOTSPOTS = {
    "name": "frontier_hotspot_analysis",
    "description": "Compute document-frequency hotspots, yearly trend slope and recent-vs-baseline burst ratios over an already-retrieved record set. Bibliometric proxy only; does not judge research value.",
    "parameters": {"type": "object", "properties": {
        **_RECORD_INPUT,
        "top_k": {"type": "integer", "minimum": 1, "maximum": 200, "description": "Rows returned; default 30"},
        "min_count": {"type": "integer", "minimum": 1, "maximum": 1000, "description": "Minimum documents per term; default 2"},
        "recent_years": {"type": "integer", "minimum": 1, "maximum": 50, "description": "Newest corpus years treated as the recent window; default 3"},
        "ngram_max": {"type": "integer", "minimum": 1, "maximum": 4, "description": "Largest word n-gram; default 2"},
        "case": {"type": "string", "maxLength": 80, "description": "Artifact subdirectory name"},
    }, **_RECORD_SOURCE},
}

GAPS = {
    "name": "frontier_gap_analysis",
    "description": "Report under-observed domain x method co-occurrence cells as candidate research gaps, with observed/expected counts. Absence in one corpus is not proof a gap is unexplored.",
    "parameters": {"type": "object", "properties": {
        **_RECORD_INPUT,
        "domain_terms": {"type": "array", "items": {"type": "string"}, "maxItems": 200,
                         "description": "Domain terms to cross-tabulate; omit to use the bundled defaults"},
        "method_terms": {"type": "array", "items": {"type": "string"}, "maxItems": 200,
                         "description": "Method/technique terms; omit to use the bundled defaults"},
        "min_support": {"type": "integer", "minimum": 0, "maximum": 1000, "description": "Max observed count still treated as under-observed; default 2"},
        "min_expected": {"type": "number", "minimum": 0, "maximum": 100000, "description": "Minimum expected count for a cell to be considered; default 1.5"},
        "top_k": {"type": "integer", "minimum": 1, "maximum": 200, "description": "Rows returned; default 25"},
        "ngram_max": {"type": "integer", "minimum": 1, "maximum": 4},
        "case": {"type": "string", "maxLength": 80},
    }, **_RECORD_SOURCE},
}

REPORT = {
    "name": "frontier_report_build",
    "description": "Assemble previously written frontier analysis JSON artifacts into one Markdown report with an explicit methodology and limitations section. Returns the report body, so it can be reused directly. Writes only inside the plugin workspace.",
    "parameters": {"type": "object", "properties": {
        "analysis_paths": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 20,
                           "description": "Absolute paths returned by the other frontier tools"},
        "title": {"type": "string", "maxLength": 200},
        "case": {"type": "string", "maxLength": 80},
    }, "required": ["analysis_paths"]},
}
