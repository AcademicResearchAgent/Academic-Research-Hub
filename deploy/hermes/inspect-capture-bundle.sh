set -euo pipefail
sudo docker exec -i haudi-openwebui python - <<'PY'
from pathlib import Path
import re
for p in Path('/app/build/_app/immutable').rglob('*.js'):
 s=p.read_text()
 if 'cursor:"never"' not in s:continue
 print('ASSET',p.name)
 i=s.index('cursor:"never"');print(s[i-180:i+1400])
 i=s.find('Model(s) do not support file upload');print('TOAST',s[i-70:i+100])
PY
