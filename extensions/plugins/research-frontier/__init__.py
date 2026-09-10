"""Hermes plugin for bibliometric hotspot, trend and research-gap analysis."""
from __future__ import annotations

from pathlib import Path

from . import schemas, tools


def register(ctx) -> None:
    ctx.register_tool(name="frontier_corpus_profile", toolset="research_frontier",
                      schema=schemas.PROFILE, handler=tools.corpus_profile)
    ctx.register_tool(name="frontier_hotspot_analysis", toolset="research_frontier",
                      schema=schemas.HOTSPOTS, handler=tools.hotspot_analysis)
    ctx.register_tool(name="frontier_gap_analysis", toolset="research_frontier",
                      schema=schemas.GAPS, handler=tools.gap_analysis)
    ctx.register_tool(name="frontier_report_build", toolset="research_frontier",
                      schema=schemas.REPORT, handler=tools.report_build)

    skill_file = Path(__file__).parent / "skills" / "research-frontier" / "SKILL.md"
    if skill_file.exists():
        ctx.register_skill("research-frontier", skill_file)
