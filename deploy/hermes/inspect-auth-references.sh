set -euo pipefail
sudo docker exec -i haudi-openwebui python - <<'PY'
from pathlib import Path
root=Path('/app/build')
for p in root.rglob('*'):
    if p.is_file() and p.suffix in {'.js','.html'}:
        text=p.read_text()
        if '52.D9R2snhE.js' in text:
            print('Auth reference:',p)
print((root/'index.html').read_text()[-2200:])
PY
