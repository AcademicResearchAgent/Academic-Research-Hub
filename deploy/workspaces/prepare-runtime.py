"""Prepare a new isolated worker image context on the existing server.

Copies code/dependencies, never the active profile's secrets, memories or chat DB.
Does not modify or restart current services.
"""
import argparse
import json
from pathlib import Path
import shutil
import yaml

ROOT = Path('/home/ubuntu/haudi-hermes')


def prepare(destination, assets):
    destination = destination.resolve()
    if destination.parent != (ROOT / 'workspace-builds').resolve() or destination.exists():
        raise ValueError('Use a new direct child of workspace-builds')
    destination.mkdir(parents=True)
    record = json.loads((ROOT / 'extensions/deployment.json').read_text())
    release = ROOT / 'extensions/releases' / record['release']
    for name in ('venv', 'source'):
        shutil.copytree(ROOT / name, destination / name, symlinks=True,
                        ignore=shutil.ignore_patterns('.git', 'node_modules', '__pycache__', '*.log', '*.pyc', '.env', '.env.*', '.venv'))
    shutil.copytree(release, destination / 'extensions')
    # A reviewed plugin override may accompany this runtime release before the
    # shared legacy service is upgraded; it is applied only to the new image.
    latex_override = assets / 'latex-tools.py'
    if latex_override.is_file():
        shutil.copy2(latex_override, destination / 'extensions/plugins/latex-paper/tools.py')
    profile = destination / 'profile'
    profile.mkdir()
    for name in ('skills', 'plugins'):
        shutil.copytree(ROOT / 'state' / name, profile / name,
                        ignore=shutil.ignore_patterns('__pycache__', '.env', '.env.*', '*.pyc'))
    if latex_override.is_file():
        shutil.copy2(latex_override, profile / 'plugins/latex-paper/tools.py')
    shutil.copy2(ROOT / 'state/SOUL.md', profile / 'SOUL.md')
    with (profile / 'SOUL.md').open('a') as soul:
        soul.write('\n当前科研任务的文件统一存放在 /workspace。用户界面会展示文件引用，请用文件名或工作区内相对路径说明成果，不用服务器绝对路径交付。上传资料已位于当前工作区，按需读取。其他任务的文件不可访问。\n')
    active = yaml.safe_load((ROOT / 'state/config.yaml').read_text())
    # Explicit schema selection: a provider URL/key, memory or account metadata
    # from the live profile must never be baked into the shared image.
    extension = json.loads((release / 'config.json').read_text())
    config = {
        'model': {'default': 'deepseek-v4-pro', 'provider': 'custom', 'base_url': 'https://api.deepseek.com/v1'},
        'platform_toolsets': {'api_server': ['terminal', 'file', 'web', *extension['api_toolsets']]},
        'skills': {'disabled': active.get('skills', {}).get('disabled', [])},
        'plugins': {'enabled': extension['plugins'], 'disabled': []},
        'mcp_servers': {},
    }
    for name, server in extension['mcp_servers'].items():
        config['mcp_servers'][name] = {
            'command': '/opt/venv/bin/python',
            'args': [s.replace('{release}', '/opt/extensions').replace('{root}', '/opt') for s in server['args']],
            'enabled': True, 'timeout': 60, 'connect_timeout': 30,
            'supports_parallel_tool_calls': False, 'tools': server['tools'],
        }
    config['mcp_servers']['cfd_npy3d']['env'] = {
        'NPY3D_OUT_ROOT': '/workspace/可视化', 'NPY3D_SAMPLE_DIR': '/opt/examples/cfd',
        'MPLCONFIGDIR': '/state/cache/matplotlib', 'QT_QPA_PLATFORM': 'offscreen'}
    (profile / 'config.yaml').write_text(yaml.safe_dump(config, allow_unicode=True))
    shutil.copy2(assets / 'Dockerfile.runtime', destination / 'Dockerfile')
    shutil.copy2(assets / 'worker_boot.py', destination / 'worker_boot.py')
    (destination / 'provenance.json').write_text(json.dumps({'extension_release': record['release']}, indent=2))
    print(destination)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', type=Path)
    parser.add_argument('--assets', type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    prepare(args.destination, args.assets)
