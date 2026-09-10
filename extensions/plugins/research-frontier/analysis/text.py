"""Deterministic term extraction for English and Chinese records.

English text is tokenised on ASCII words; CJK runs are reduced to character bigrams
because no segmenter is bundled. Bigrams are an approximation and are documented as a
limitation in ``references/limitations.md``.
"""
from __future__ import annotations

import re
from pathlib import Path

_LATIN = re.compile(r"[a-z][a-z0-9\-]{1,}")
_CJK = re.compile(r"[\u4e00-\u9fff]+")
_STOPWORDS_FILE = Path(__file__).resolve().parents[1] / "references" / "stopwords_en.txt"

_stopwords: set[str] | None = None

# Fields read from a record when building the analysed text.
DEFAULT_TEXT_FIELDS = ("title", "keywords")
SUPPORTED_TEXT_FIELDS = ("title", "abstract", "keywords", "venue")


def stopwords() -> set[str]:
    global _stopwords
    if _stopwords is None:
        if _STOPWORDS_FILE.is_file():
            lines = _STOPWORDS_FILE.read_text(encoding="utf-8").splitlines()
            _stopwords = {line.strip().lower() for line in lines if line.strip() and not line.startswith("#")}
        else:
            _stopwords = set()
    return _stopwords


def record_text(record: dict, text_fields) -> str:
    """Join the requested record fields into one newline-separated string.

    Each keyword and each field stays on its own line so n-grams cannot span a boundary
    and invent phrases such as "learning crispr".
    """
    segments = []
    for field in text_fields:
        value = record.get(field)
        if not value:
            continue
        if isinstance(value, (list, tuple)):
            segments.extend(str(item) for item in value if item)
        else:
            segments.append(str(value))
    return "\n".join(segments)


def _latin_words(text: str) -> list[str]:
    return [match.group() for match in _LATIN.finditer(text)]


def _cjk_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for run in _CJK.findall(text):
        if len(run) == 1:
            terms.add(run)
        else:
            terms.update(run[index:index + 2] for index in range(len(run) - 1))
    return terms


def record_terms(text: str, ngram_max: int = 1) -> set[str]:
    """Return the distinct terms for one record.

    Each newline-separated segment is tokenised on its own. N-grams are built from the raw
    word sequence so adjacency is preserved, then any gram containing a stopword is
    discarded. CJK bigrams are added without expansion.
    """
    stops = stopwords()
    terms: set[str] = set()
    for segment in (text or "").split("\n"):
        lowered = segment.lower()
        words = _latin_words(lowered)
        terms.update(word for word in words if word not in stops)
        if ngram_max > 1:
            for size in range(2, ngram_max + 1):
                for index in range(len(words) - size + 1):
                    gram = words[index:index + size]
                    if any(word in stops for word in gram):
                        continue
                    terms.add(" ".join(gram))
        terms.update(_cjk_terms(lowered))
    return terms


def normalize_term(term: str) -> str:
    """Normalise a caller-supplied term so it matches the token representation."""
    return " ".join(str(term or "").lower().split())


def term_is_present(term: str, terms: set[str], text: str) -> bool:
    """True when a domain/method term occurs as a token, n-gram or substring."""
    normalized = normalize_term(term)
    if not normalized:
        return False
    if normalized in terms:
        return True
    lowered = (text or "").lower()
    if " " in normalized:
        return normalized in lowered
    return re.search(r"(?<![a-z0-9])" + re.escape(normalized) + r"(?![a-z0-9])", lowered) is not None
