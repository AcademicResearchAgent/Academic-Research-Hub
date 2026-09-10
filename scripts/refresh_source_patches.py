"""Regenerate overlays while retaining the exact previously applied patch for rollback."""
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    subprocess.run([sys.executable, str(ROOT / 'scripts/prepare_sources.py'), '--check'], check=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = ROOT / '.build/patch-history' / stamp
    backup.mkdir(parents=True)
    patches = {}
    for project, filename in [('hermes-agent', '0001-workstation-identity.patch'), ('open-webui', '0001-workstation-copy.patch')]:
        current = ROOT / 'patches' / project / filename
        saved = backup / (project + '.patch')
        saved.write_bytes(current.read_bytes())
        patches[project] = (current, saved)
    subprocess.run([sys.executable, str(ROOT / 'scripts/render_product_patches.py')], check=True)
    for project, (current, saved) in patches.items():
        args = ['git', '-C', str(ROOT / 'reference' / project), 'apply']
        if current.read_bytes() == saved.read_bytes():
            continue
        subprocess.run(args + ['--reverse', '--check', str(saved)], check=True)
        subprocess.run(args + ['--reverse', str(saved)], check=True)
        try:
            subprocess.run(args + ['--check', str(current)], check=True)
            subprocess.run(args + [str(current)], check=True)
        except BaseException:
            subprocess.run(args + [str(saved)], check=True)
            current.write_bytes(saved.read_bytes())
            raise
    print('Previous patches retained:', backup)


if __name__ == '__main__':
    main()
