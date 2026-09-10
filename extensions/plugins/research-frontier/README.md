# research-frontier

Hermes plugin for bibliometric analysis of **already retrieved** literature records.

It does not search databases, read credentials, or access the network. Retrieval stays with
the `research_papers` and `ars_resolvers` MCP services; this plugin only computes over a
record set the agent already has.

## Tools

| Tool | Purpose |
| --- | --- |
| `frontier_corpus_profile` | Validate and summarise records before any analysis (year range, field coverage, duplicate DOIs). |
| `frontier_hotspot_analysis` | Document-frequency hotspots, yearly trend slope, recent-vs-baseline burst ratio. |
| `frontier_gap_analysis` | Candidate research gaps from under-observed domain x method co-occurrence cells. |
| `frontier_report_build` | Assemble the analysis artifacts into one Markdown report with method limits. |

## Input

Records come from a JSON / JSONL file (`records_path`) or inline (`records`). Each record:

```json
{"title": "...", "abstract": "...", "year": 2021, "doi": "10.1/abc", "keywords": ["..."], "venue": "..."}
```

Only `title` is required; a record without a usable title is dropped and counted.

## Output

Artifacts are written under `RESEARCH_FRONTIER_WORKSPACE` (default: a `research-frontier`
directory in the system temp dir), in `cases/<case>/`. Tool results are JSON containing the
artifact paths; `frontier_report_build` additionally returns the full Markdown body as
`report`, so it can be passed straight to a writing step.

## Scope limits

Results are bibliometric proxies, not research-value judgements. See
`references/metrics.md` and `references/limitations.md`; the bundled
`skills/research-frontier/SKILL.md` tells the agent how to report them.
