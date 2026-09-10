"""Exercise the Hermes registry and real MCP tools; no model key or LLM call required."""
import argparse
import json
import os
from pathlib import Path
import sys


def payload(value):
    """MCP wrappers may return a JSON string, a text block or structuredContent."""
    if isinstance(value, str):
        return payload(json.loads(value))
    if isinstance(value, dict):
        if value.get("error") or value.get("isError"):
            raise AssertionError("Tool reported an error")
        if "source" in value or "success" in value:
            return value
        if "result" in value:
            return payload(value["result"])
        if value.get("structuredContent"):
            return payload(value["structuredContent"])
        if value.get("content"):
            return payload(value["content"])
    if isinstance(value, list):
        for block in value:
            if isinstance(block, dict) and block.get("type") == "text":
                return payload(block["text"])
    raise AssertionError("Unexpected tool result structure")


def main(root):
    os.environ["HERMES_HOME"] = str(root / "state")
    sys.path.insert(0, str(root / "source"))
    import yaml
    from hermes_cli.plugins import discover_plugins
    from hermes_cli.tools_config import _get_platform_tools
    from tools.mcp_tool_discovery import discover_mcp_tools
    from tools.mcp_tool_lifecycle import shutdown_mcp_servers
    from tools.skills_tool import skill_view
    from model_tools import get_tool_definitions, handle_function_call
    config = yaml.safe_load((root / "state/config.yaml").read_text())
    discover_plugins()
    try:
        discover_mcp_tools(allowed_mcp_names=["research_papers", "ars_resolvers"])
        # Restrict this check to the installed extension surface. Checking every
        # optional builtin provider can trigger unrelated readiness network probes.
        enabled = sorted(_get_platform_tools(config, "api_server") & {"skills", "research_citations", "research_papers", "ars_resolvers", "research_frontier"})
        defs = get_tool_definitions(enabled_toolsets=enabled, quiet_mode=True, skip_tool_search_assembly=True)
        names = {d["function"]["name"] for d in defs}
        expected = {"skill_view", "research_citation", *("mcp__research_papers__" + n for n in
                    ("crossref_search", "crossref_lookup", "europepmc_search", "europepmc_fulltext")),
                    *("mcp__ars_resolvers__" + n for n in
                    ("openalex_verify", "semantic_scholar_verify", "arxiv_verify", "chinese_literature_verify")),
                    "frontier_corpus_profile", "frontier_hotspot_analysis",
                    "frontier_gap_analysis", "frontier_report_build"}
        assert expected <= names, f"Missing tools: {sorted(expected - names)}"
        skill = json.loads(skill_view("research-literature"))
        assert "mcp__research_papers__crossref_search" in json.dumps(skill) and not skill.get("error")

        def call(name, args):
            return payload(handle_function_call(name, args, enabled_tools=sorted(names), enabled_toolsets=enabled))

        crossref = call("mcp__research_papers__crossref_search", {"query": "CRISPR", "limit": 1})
        assert crossref["records"] and crossref["records"][0]["doi"]
        paper = call("mcp__research_papers__crossref_lookup", {"doi": crossref["records"][0]["doi"]})["record"]
        assert paper["doi"].lower() == crossref["records"][0]["doi"].lower()
        ep = call("mcp__research_papers__europepmc_search", {"query": "CRISPR OPEN_ACCESS:Y", "limit": 3})
        open_paper = next(p for p in ep["records"] if p.get("pmcid"))
        fulltext = call("mcp__research_papers__europepmc_fulltext", {"pmcid": open_paper["pmcid"], "max_chars": 1000})
        assert fulltext["evidence_level"] == "fulltext_excerpt" and fulltext["text"]
        citation = call("research_citation", {"title": paper["title"], "doi": paper["doi"]})
        assert citation["success"] and paper["doi"] in citation["source_url"]
        frontier = call("frontier_hotspot_analysis", {
            "records": [{"title": "CRISPR screening", "year": 2020, "keywords": ["crispr"]},
                        {"title": "Machine learning for CRISPR", "year": 2024, "keywords": ["machine learning", "crispr"]}],
            "text_fields": ["keywords"], "case": "verify"})
        assert frontier["success"] and frontier["terms"], "frontier plugin produced no terms"
        report = {"status": "pass", "tools": sorted(expected), "crossref_doi": paper["doi"],
                  "frontier_top_term": frontier["terms"][0]["term"],
                  "europepmc_pmcid": open_paper["pmcid"], "fulltext_chars": len(fulltext["text"]),
                  "skill_loaded": "research-literature", "citation_verified_by_plugin": citation["verified"]}
        (root / "extensions/verification.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report))
    finally:
        shutdown_mcp_servers()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/ubuntu/haudi-hermes"))
    main(parser.parse_args().root.resolve())
