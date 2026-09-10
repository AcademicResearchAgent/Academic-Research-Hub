"""Load, validate and profile retrieved bibliographic records.

Only ``title`` is mandatory. Missing facts are recorded as missing; nothing is inferred
or invented, and no network access happens here.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from . import text

MAX_RECORDS = 20000
MAX_BYTES = 20 * 1024 * 1024
MIN_YEAR, MAX_YEAR = 1500, 2100
_DOI_PREFIX = "https://doi.org/"
_KNOWN_FIELDS = ("title", "abstract", "year", "doi", "keywords", "authors", "venue", "language")


class InputError(ValueError):
    """Raised for malformed input; callers turn this into a JSON error result."""


def _clean_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        value = " ".join(str(item) for item in value)
    cleaned = " ".join(str(value).split())
    return cleaned or None


def _clean_year(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        year = value
    elif isinstance(value, float):
        year = int(value)
    else:
        leading = str(value).strip()[:4]
        if not leading.isdigit():
            return None
        year = int(leading)
    return year if MIN_YEAR <= year <= MAX_YEAR else None


def _clean_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    cleaned = []
    for item in value:
        entry = _clean_text(item)
        if entry and entry not in cleaned:
            cleaned.append(entry)
    return cleaned


def _clean_doi(value) -> str | None:
    doi = _clean_text(value)
    if not doi:
        return None
    if doi.lower().startswith(_DOI_PREFIX):
        doi = doi[len(_DOI_PREFIX):]
    return doi


def normalize_records(raw_records) -> tuple[list[dict], list[dict]]:
    """Return (usable records, dropped records) without inventing any field."""
    if not isinstance(raw_records, list):
        raise InputError("records must be an array of objects")
    if len(raw_records) > MAX_RECORDS:
        raise InputError(f"records must not exceed {MAX_RECORDS} entries")
    usable, dropped = [], []
    for index, raw in enumerate(raw_records):
        if not isinstance(raw, dict):
            dropped.append({"index": index, "reason": "not an object"})
            continue
        title = _clean_text(raw.get("title"))
        if not title:
            dropped.append({"index": index, "reason": "missing title"})
            continue
        usable.append({
            "title": title,
            "abstract": _clean_text(raw.get("abstract")),
            "year": _clean_year(raw.get("year")),
            "doi": _clean_doi(raw.get("doi")),
            "keywords": _clean_list(raw.get("keywords")),
            "authors": _clean_list(raw.get("authors")),
            "venue": _clean_text(raw.get("venue")),
            "language": _clean_text(raw.get("language")),
        })
    return usable, dropped


def _parse_jsonl(content: str) -> list:
    records = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise InputError(f"records file is not valid JSONL: {exc}") from None
    return records


def _read_records_file(records_path) -> list:
    path = Path(str(records_path)).expanduser()
    if not path.is_file():
        raise InputError("records_path does not point to a readable file")
    if path.stat().st_size > MAX_BYTES:
        raise InputError(f"records file must not exceed {MAX_BYTES // (1024 * 1024)} MB")
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise InputError(f"records file could not be read as UTF-8 text: {exc}") from None
    if path.suffix.lower() == ".jsonl":
        return _parse_jsonl(content)
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return _parse_jsonl(content)
    if isinstance(payload, dict):
        payload = payload.get("records", [])
    if not isinstance(payload, list):
        raise InputError("records file must contain an array, or an object with a records array")
    return payload


def load_records(*, records=None, records_path=None) -> tuple[list[dict], list[dict]]:
    if records is not None:
        raw = records
    elif records_path:
        raw = _read_records_file(records_path)
    else:
        raise InputError("records_path or records is required")
    return normalize_records(raw)


def resolve_text_fields(text_fields) -> tuple[str, ...]:
    if not text_fields:
        return text.DEFAULT_TEXT_FIELDS
    if not isinstance(text_fields, (list, tuple)) or not all(isinstance(f, str) for f in text_fields):
        raise InputError("text_fields must be an array of strings")
    unknown = [f for f in text_fields if f not in text.SUPPORTED_TEXT_FIELDS]
    if unknown:
        raise InputError("unsupported text_fields: " + ", ".join(sorted(unknown)))
    return tuple(dict.fromkeys(text_fields))


def profile(records: list[dict], dropped: list[dict], text_fields) -> dict:
    """Summarise coverage and obvious defects. Purely descriptive, sorted and stable."""
    total = len(records)
    missing = {field: sum(1 for record in records if not record.get(field))
               for field in ("year", "abstract", "doi", "keywords", "authors", "venue")}
    years = sorted(record["year"] for record in records if record["year"])
    dois = Counter(record["doi"] for record in records if record["doi"])
    duplicates = sorted(doi for doi, count in dois.items() if count > 1)
    warnings = []
    if missing["year"]:
        warnings.append(f"{missing['year']} of {total} records have no usable year; trends ignore them.")
    if missing["abstract"]:
        warnings.append(f"{missing['abstract']} of {total} records have no abstract.")
    if duplicates:
        warnings.append(f"{len(duplicates)} DOI values appear more than once; deduplicate before drawing size conclusions.")
    if text_fields == ("title",) and total < 50:
        warnings.append("Title-only term extraction on a small corpus yields weak hotspots.")
    return {
        "record_count": total,
        "dropped_count": len(dropped),
        "dropped": dropped[:20],
        "year_min": years[0] if years else None,
        "year_max": years[-1] if years else None,
        "years_with_data": len(set(years)),
        "missing": missing,
        "duplicate_dois": duplicates[:50],
        "text_fields": list(text_fields),
        "warnings": warnings,
    }
