"""Executed inside an actual worker: synthetic artifacts, no model credentials."""
import base64
import io
import json
from pathlib import Path
import uuid
import zipfile

import yaml
from hermes_cli.plugins import discover_plugins
from hermes_cli.tools_config import _get_platform_tools
from tools.mcp_tool_discovery import discover_mcp_tools
from tools.mcp_tool_lifecycle import shutdown_mcp_servers
from tools.skills_tool import skill_view, skills_list
from model_tools import get_tool_definitions, handle_function_call


def unpack(value):
    if isinstance(value, str):
        try:
            return unpack(json.loads(value))
        except ValueError:
            return {'text': value}
    if isinstance(value, list):
        return unpack(next(b['text'] for b in value if b.get('type') == 'text'))
    assert not value.get('error') and not value.get('isError'), value
    if 'success' in value or 'source' in value:
        assert value.get('success') is not False, value
        return value
    for key in ('result', 'structuredContent', 'content'):
        if value.get(key):
            return unpack(value[key])
    return value


def main():
    config = yaml.safe_load(Path('/state/config.yaml').read_text())
    discover_plugins()
    visible = json.loads(skills_list())['skills']
    for name in ('research-literature', 'npy3d-visualization', 'latex-paper'):
        assert not json.loads(skill_view(name)).get('error')
    try:
        discover_mcp_tools(allowed_mcp_names=['research_papers', 'ars_resolvers', 'cfd_npy3d'])
        enabled = sorted(_get_platform_tools(config, 'api_server') & {'skills', 'research_citations', 'research_papers', 'ars_resolvers', 'cfd_npy3d', 'latex_paper'})
        definitions = get_tool_definitions(enabled_toolsets=enabled, quiet_mode=True, skip_tool_search_assembly=True)
        names = {d['function']['name'] for d in definitions}

        def call(name, args):
            assert name in names, 'Missing registered extension: ' + name
            return unpack(handle_function_call(name, args, enabled_tools=sorted(names), enabled_toolsets=enabled))

        source = '\\documentclass{article}\n\\begin{document}\nSynthetic test only.\n\\end{document}\n'
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('main.tex', source)
        template = call('latex_template_inspect', {'template_zip_base64': base64.b64encode(buffer.getvalue()).decode()})
        assert template['main_file'] == 'main.tex'
        # Recreate a persisted project without an in-memory plugin registry.
        # This tests reopening, validation and packaging, not LLM generation.
        project_id = uuid.uuid4().hex
        project = Path('/workspace/论文工程') / project_id
        project.mkdir(parents=True)
        (project / 'main.tex').write_text(source)
        (project / '.latex-paper.json').write_text(json.dumps({'main_file': 'main.tex', 'recipe': 'xelatex-bibtex', 'confirmed': False}))
        validation = call('latex_project_validate', {'project_id': project_id})
        assert validation['valid']
        packaged = call('latex_project_confirm_package', {'project_id': project_id, 'confirmed': True})
        archive_path = Path(packaged['archive_path'])
        assert archive_path.resolve().is_relative_to(Path('/workspace'))
        with zipfile.ZipFile(archive_path) as archive:
            assert archive.read('main.tex').decode() == source
        inspected = call('mcp__cfd_npy3d__npy3d_inspect', {'data_dir': '/opt/examples/cfd'})
        assert inspected
        call('mcp__cfd_npy3d__npy3d_render_surface', {'data_dir': '/opt/examples/cfd', 'case': 'isolated-check', 'frame': 0, 'channels': '0'})
        call('mcp__cfd_npy3d__npy3d_render_animation', {'data_dir': '/opt/examples/cfd', 'case': 'isolated-check', 'channel': 0, 'max_frames': 4, 'fps': 2})
        from PIL import Image
        pngs = list(Path('/workspace').rglob('*.png'))
        gifs = list(Path('/workspace').rglob('*.gif'))
        assert pngs and gifs
        with Image.open(pngs[0]) as image:
            image.verify()
        with Image.open(gifs[0]) as image:
            assert image.n_frames > 1
            frames = image.n_frames
        # A real stdio resolver call that requires no external network.
        skipped = call('mcp__ars_resolvers__chinese_literature_verify', {'entry': {'title': 'English synthetic fixture', 'container_title': 'English Journal'}})
        assert skipped.get('status') == 'skipped'
        report = {'skills_visible': len(visible), 'skill_loads': 3, 'mcp_registered': sorted(n for n in names if n.startswith('mcp__')),
                  'latex_template_inspected': True, 'latex_persisted_project_reopened': True, 'latex_zip_verified': True,
                  'cfd_png_decoded': True, 'cfd_gif_frames': frames, 'ars_stdio_call': True,
                  'llm_called': False, 'scope': 'Real worker registry, stdio MCP rendering, plugin validation and packaging. No auxiliary LLM generation.'}
        Path('/workspace/extension-check.json').write_text(json.dumps(report, indent=2))
        print('EXTENSIONS_RESULT=' + json.dumps(report), flush=True)
    finally:
        shutdown_mcp_servers()


if __name__ == '__main__':
    main()
