"""Exercise the Hermes registry and real MCP tools; no model key or LLM call required."""
import argparse
import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import zipfile


def payload(value):
    """MCP wrappers may return a JSON string, a text block or structuredContent."""
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            return {"text": value}
        return payload(decoded)
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
    from tools.skills_tool import skill_view, skills_list
    from model_tools import get_tool_definitions, handle_function_call
    config = yaml.safe_load((root / "state/config.yaml").read_text())
    discover_plugins()
    skill_scope = None
    release_config = Path(__file__).with_name("config.json")
    if release_config.is_file():
        extension = json.loads(release_config.read_text())
        if "skill_policy" in extension:
            allowed = set(extension["skills"]) | set(extension["skill_policy"]["include_upstream"]) | {"hermes-agent"}
            visible = {s["name"] for s in json.loads(skills_list())["skills"]}
            assert not visible - allowed, f"Unexpected skills: {sorted(visible - allowed)}"
            assert set(extension["skills"]) <= visible, "Managed research skills must remain visible"
            for name in visible:
                assert not json.loads(skill_view(name)).get("error"), "Cannot load visible skill: " + name
            for name in config["skills"].get("workstation_managed_disabled", []):
                assert json.loads(skill_view(name)).get("error"), "Excluded skill still loads: " + name
            skill_scope = {"visible": sorted(visible), "count": len(visible), "excluded_loads_blocked": True}
    try:
        discover_mcp_tools(allowed_mcp_names=["research_papers", "ars_resolvers", "cfd_npy3d"])
        # Restrict this check to the installed extension surface. Checking every
        # optional builtin provider can trigger unrelated readiness network probes.
        enabled = sorted(_get_platform_tools(config, "api_server") & {"skills", "research_citations", "research_papers", "ars_resolvers", "cfd_npy3d", "latex_paper", "research_frontier"})
        defs = get_tool_definitions(enabled_toolsets=enabled, quiet_mode=True, skip_tool_search_assembly=True)
        names = {d["function"]["name"] for d in defs}
        expected = {"skill_view", "research_citation", *("mcp__research_papers__" + n for n in
                    ("crossref_search", "crossref_lookup", "europepmc_search", "europepmc_fulltext")),
                    *("mcp__ars_resolvers__" + n for n in
                    ("openalex_verify", "semantic_scholar_verify", "arxiv_verify", "chinese_literature_verify"))}
        expected.update("mcp__cfd_npy3d__" + n for n in config["mcp_servers"]["cfd_npy3d"]["tools"]["include"])
        expected.update(("latex_template_inspect", "latex_project_generate", "latex_project_validate", "latex_project_confirm_package"))
        expected.update(("frontier_corpus_profile", "frontier_hotspot_analysis", "frontier_gap_analysis", "frontier_report_build"))
        assert expected <= names, f"Missing tools: {sorted(expected - names)}"
        skill = json.loads(skill_view("research-literature"))
        assert "mcp__research_papers__crossref_search" in json.dumps(skill) and not skill.get("error")
        loaded_skills = ["research-literature"]
        for name, tool in (("npy3d-visualization", "mcp__cfd_npy3d__npy3d_render_surface"),
                           ("pvdata-visualization", "mcp__cfd_npy3d__pvdata_render_scatter3d"),
                           ("pvdata-import", "mcp__cfd_npy3d__pvdata_import"),
                           ("cfd-web-visualization", "mcp__cfd_npy3d__npy3d_web_viewer")):
            loaded = json.loads(skill_view(name))
            assert tool in json.dumps(loaded) and not loaded.get("error"), f"skill {name} failed to load"
            loaded_skills.append(name)
        for name in ("ars-deep-research", "ars-academic-paper", "ars-academic-paper-reviewer", "ars-academic-pipeline", "npy3d-visualization", "pvdata-import", "pvdata-visualization", "latex-paper", "research-frontier"):
            assert not json.loads(skill_view(name)).get("error"), "Skill missing: " + name

        def call(name, args):
            return payload(handle_function_call(name, args, enabled_tools=sorted(names), enabled_toolsets=enabled))

        fixture = io.BytesIO()
        with zipfile.ZipFile(fixture, 'w') as archive:
            archive.writestr('main.tex', '\\documentclass{article}\n\\begin{document}Test\\end{document}')
        latex = call('latex_template_inspect', {'template_zip_base64': base64.b64encode(fixture.getvalue()).decode()})
        assert latex['success'] and latex['main_file'] == 'main.tex'
        skipped = call('mcp__ars_resolvers__chinese_literature_verify', {'entry': {'title': 'English fixture', 'container_title': 'English Journal'}})
        assert skipped.get('status') == 'skipped'
        cfd_root = Path(config['mcp_servers']['cfd_npy3d']['args'][0]).parent
        spec = importlib.util.spec_from_file_location('extension_sample', cfd_root / 'make_sample.py')
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        generator.T, generator.W, generator.H = 4, 61, 31
        examples = root / 'workspace/examples/cfd'
        generator.generate(str(examples))
        latex_examples = root / 'workspace/examples/latex'
        latex_examples.mkdir(parents=True, exist_ok=True)
        (latex_examples / 'template.zip').write_bytes(fixture.getvalue())
        inspected = call('mcp__cfd_npy3d__npy3d_inspect', {})
        assert inspected.get('text') or inspected.get('result')
        rendered = call('mcp__cfd_npy3d__npy3d_render_surface', {'data_dir': str(examples), 'case': 'deployment-check'})
        assert '.png' in json.dumps(rendered)

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
                  "skill_loaded": "research-literature", "skills_loaded": loaded_skills,
                  "citation_verified_by_plugin": citation["verified"]}
        report.update({'latex_template_inspected': True, 'cfd_rendered': True, 'ars_registered': True, 'skills_loaded': 10})
        report['skill_scope'] = skill_scope
        (root / "extensions/verification.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report))
    finally:
        shutdown_mcp_servers()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/ubuntu/haudi-hermes"))
    main(parser.parse_args().root.resolve())
