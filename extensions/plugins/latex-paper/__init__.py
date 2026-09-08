"""Hermes plugin for prompt-driven LaTeX project generation and packaging."""
from __future__ import annotations

from pathlib import Path

from . import schemas, tools


def register(ctx) -> None:
    ctx.register_tool(name="latex_template_inspect", toolset="latex_paper", schema=schemas.INSPECT, handler=tools.inspect_template)
    ctx.register_tool(name="latex_project_generate", toolset="latex_paper", schema=schemas.GENERATE, handler=lambda args, **kwargs: tools.generate_project(ctx, args, **kwargs))
    ctx.register_tool(name="latex_project_validate", toolset="latex_paper", schema=schemas.VALIDATE, handler=tools.validate_project)
    ctx.register_tool(name="latex_project_confirm_package", toolset="latex_paper", schema=schemas.PACKAGE, handler=tools.confirm_package)

    skill_file = Path(__file__).parent / "skills" / "latex-paper" / "SKILL.md"
    if skill_file.exists():
        ctx.register_skill("latex-paper", skill_file)
