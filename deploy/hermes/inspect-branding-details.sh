set -euo pipefail
sudo docker exec -i haudi-openwebui python - <<'PY'
from pathlib import Path
s=Path('/app/backend/open_webui/main.py').read_text().splitlines()
print('\n'.join(s[2820:2915]))
p=Path('/app/build/_app/immutable/nodes/2.DY2zKRtP.js')
s=p.read_text(); needle='includes("Open WebUI")'; i=s.find(needle)
print('ABOUT CONTEXT:',s[i-2400:i+500])
p=Path('/app/build/_app/immutable/nodes/52.D9R2snhE.js')
s=p.read_text(); i=s.find('uppercase opacity-35')
print('LOGIN CONTEXT:',s[i-100:i+200])
PY
