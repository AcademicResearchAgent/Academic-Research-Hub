# 指标口径 / Metric definitions

All figures are computed over one supplied record set. Nothing is fetched.

## Terms

- Text is split per field and per keyword (newline-separated segments), so n-grams never span
  a field or keyword boundary.
- Latin tokens: `[a-z][a-z0-9-]{1,}`, lower-cased. Stopwords from `stopwords_en.txt` are dropped.
- Word n-grams of size 2..`ngram_max` are built **before** stopword removal so real adjacency is
  kept, then any gram containing a stopword is discarded.
- CJK runs become character bigrams (no segmenter is bundled).
- Terms are surface forms: `crispr` and `CRISPR-Cas9` are counted separately.

## Hotspots (`frontier_hotspot_analysis`)

| Metric | Definition |
| --- | --- |
| `documents` | Number of records whose text contains the term (document frequency) |
| `share` | `documents / records` |
| `idf` | `ln(records / documents)` — ranking help only, not a corpus-independent weight |
| `trend_slope` | Least-squares slope of yearly document counts; `null` when fewer than 3 distinct years |
| `recent_rate` | Term documents in the recent window / documents in the recent window |
| `prior_rate` | Same, for all earlier years |
| `burst_ratio` | `recent_rate / prior_rate`; `null` when there is no earlier window or the term was absent before |

The recent window is the newest `recent_years` distinct years **present in the corpus**, anchored
on `year_max`. This keeps a fixed input reproducible.

## Candidate gaps (`frontier_gap_analysis`)

Presence matrix over records x (domain + method terms). `term_is_present` matches a whole token,
an n-gram, or a substring for multi-word terms.

| Metric | Definition |
| --- | --- |
| `observed` | Records containing both terms |
| `expected` | `domain_documents * method_documents / records` |
| `residual` | Pearson residual `(observed - expected) / sqrt(expected)` |

- Candidate gap: `expected >= min_expected`, `observed <= min_support`, `residual < 0`.
- Dense pair: `residual > 0`.
- `sparse_domains`: domain terms with the lowest document counts.

A negative residual means the corpus under-represents that combination relative to the marginals.
It is **not** evidence that the combination is unexplored in the literature.
