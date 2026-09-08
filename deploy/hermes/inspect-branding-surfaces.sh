set -euo pipefail
sudo docker exec -i haudi-openwebui python - <<'PY'
from pathlib import Path
import re
for filename in ('/app/build/index.html','/app/build/manifest.json','/app/build/manifest.webmanifest','/app/backend/open_webui/main.py'):
 p=Path(filename)
 if p.exists():
  for n,line in enumerate(p.read_text().splitlines(),1):
   if 'Open WebUI' in line or 'manifest' in line and p.name=='index.html':print(str(p),n,line[:350])
root=Path('/app/build/_app/immutable')
count=0
for p in root.rglob('*.js'):
 s=p.read_text()
 if 'Open WebUI' in s and not 'haudi-research-v1' in p.name:
  count+=1
  contexts=[s[max(0,m.start()-75):m.end()+120] for m in re.finditer('Open WebUI',s)]
  print(p.name,contexts[:4])
  if count>=35:break
print('Listed matching assets:',count)
PY
