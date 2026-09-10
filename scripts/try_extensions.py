"""Local MCP smoke test and synthetic CFD demo; --online also probes public indexes.

No model key, production profile or server deployment is used. Outputs live in .build.
"""
import argparse
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
import importlib.util
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.build/local-extension-trial'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def payload(result):
    if result.isError:
        raise RuntimeError('MCP tool returned an error')
    if result.structuredContent:
        return result.structuredContent
    for block in result.content:
        if block.type == 'text':
            try:
                return json.loads(block.text)
            except ValueError:
                return {'text': block.text}
    return {}


@asynccontextmanager
async def session(service):
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1',
           'NPY3D_OUT_ROOT': str(OUT / 'cfd'), 'MPLCONFIGDIR': str(OUT / 'matplotlib')}
    params = StdioServerParameters(command=sys.executable,
        args=[str(ROOT / 'extensions/mcp' / service / 'server.py')], env=env, cwd=str(ROOT))
    with (OUT / (service + '.log')).open('w', encoding='utf-8') as log:
        async with stdio_client(params, errlog=log) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=100)) as client:
                await client.initialize()
                yield client


async def main(online):
    OUT.mkdir(parents=True, exist_ok=True)
    report = {'tested_at': datetime.now(timezone.utc).isoformat(), 'python': sys.executable, 'online': online}
    def save():
        (OUT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    config = {'mcpServers': {name: {'command': sys.executable,
              'args': [str(ROOT / 'extensions/mcp' / path / 'server.py')],
              'env': {'PYTHONUTF8': '1', 'NPY3D_OUT_ROOT': str(OUT / 'cfd')}}
              for name, path in [('research_papers', 'paper-search'), ('ars_resolvers', 'ars-resolvers'), ('cfd_npy3d', 'cfd-npy3d')]}}
    (OUT / 'mcp.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    generator = load('trial_sample', ROOT / 'extensions/mcp/cfd-npy3d/make_sample.py')
    # Keep the local smoke fixture small. This is synthetic data, never research evidence.
    generator.T, generator.W, generator.H = 4, 61, 31
    generator.generate(str(OUT / 'synthetic-data'))
    async with session('cfd-npy3d') as client:
        names = [t.name for t in (await client.list_tools()).tools]
        assert len(names) == 7, names
        for name, args in [
            ('npy3d_inspect', {'data_dir': str(OUT / 'synthetic-data')}),
            ('npy3d_render_surface', {'data_dir': str(OUT / 'synthetic-data'), 'channels': '0', 'case': 'synthetic_trial'}),
            ('npy3d_render_animation', {'data_dir': str(OUT / 'synthetic-data'), 'channel': 0, 'max_frames': 4, 'case': 'synthetic_trial'})]:
            result = payload(await client.call_tool(name, args))
            report[name] = result
            print(name + ': MCP call passed', flush=True)
            save()
    pngs, gifs = list((OUT / 'cfd').rglob('*.png')), list((OUT / 'cfd').rglob('*.gif'))
    assert pngs and gifs, 'CFD render did not create outputs'
    report['artifacts'] = [str(p) for p in pngs + gifs]
    bridge = load('trial_pvbridge', ROOT / 'extensions/mcp/cfd-npy3d/pvbridge.py')
    report['paraview_available'] = bridge.available()
    print('ParaView available:', report['paraview_available'], flush=True)
    async with session('paper-search') as client:
        names = [t.name for t in (await client.list_tools()).tools]
        assert len(names) == 4, names
        report['paper_tools'] = names
    async with session('ars-resolvers') as client:
        names = [t.name for t in (await client.list_tools()).tools]
        assert len(names) == 4, names
        report['ars_tools'] = names
        skipped = payload(await client.call_tool('chinese_literature_verify', {'entry': {'title': 'An English-only citation', 'container_title': 'English Journal'}}))
        assert skipped.get('status') == 'skipped', skipped
        report['chinese_skip'] = skipped
        save()
        if online:
            report['public_indexes'] = {}
            for name, entry in [
                ('arxiv_verify', {'arxiv_id': '1706.03762', 'title': 'Attention Is All You Need'}),
                ('openalex_verify', {'doi': '10.1038/s41592-023-01840-z', 'title': 'Improving the sensitivity of in vivo CRISPR off-target detection with DISCOVER-Seq.'}),
                ('semantic_scholar_verify', {'doi': '10.1038/s41592-023-01840-z', 'title': 'Improving the sensitivity of in vivo CRISPR off-target detection with DISCOVER-Seq.'})]:
                print('Checking public index: ' + name, flush=True)
                try:
                    result = payload(await client.call_tool(name, {'entry': entry}))
                    report['public_indexes'][name] = result
                    print(json.dumps({'tool': name, 'matched': result.get('matched'), 'degraded': result.get('degraded', False), 'source': result.get('source')}, ensure_ascii=False), flush=True)
                except Exception as exc:
                    report['public_indexes'][name] = {'failed': True, 'error_type': type(exc).__name__}
                    print(name + ': failed (' + type(exc).__name__ + ')', flush=True)
                save()
    report['mcp_smoke_passed'] = True
    save()
    print('Report: ' + str(OUT / 'report.json'), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--online', action='store_true', help='Probe public scholarly APIs without a model or API key')
    asyncio.run(main(parser.parse_args().online))
