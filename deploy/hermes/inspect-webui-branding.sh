set -euo pipefail
sudo docker exec -i haudi-openwebui python - <<'PY'
from pathlib import Path
import sqlite3
for p in (Path('/app/LICENSE'),Path('/app/backend/LICENSE'),Path('/app/backend/open_webui/env.py')):
    if not p.exists():continue
    print('FILE:',str(p))
    lines=p.read_text().splitlines()
    if p.name=='LICENSE':print('\n'.join(lines[:140]))
    else:
        hits=[i for i,line in enumerate(lines) if 'WEBUI_NAME' in line or 'CUSTOM_NAME' in line or 'LICENSE' in line]
        for i in hits:
            print('\n'.join(f'{j+1}: {lines[j]}' for j in range(max(0,i-2),min(len(lines),i+6))))
db=sqlite3.connect('file:/app/backend/data/webui.db?mode=ro',uri=True)
print('Total registered users:',db.execute('SELECT COUNT(*) FROM user').fetchone()[0])
db.close()
PY
