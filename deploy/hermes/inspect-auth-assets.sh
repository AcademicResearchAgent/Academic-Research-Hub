set -euo pipefail
sudo docker exec -i haudi-openwebui python - <<'PY'
from pathlib import Path
root=Path('/app/build')
print('Frontend root exists:',root.exists())
for p in root.rglob('*.js'):
    if not p.is_file(): continue
    t=p.read_text()
    if 'auth-login-card' in t:
        print('Auth component:',p,'bytes:',len(t))
        for needle in ['Sign in to {{WEBUI_NAME}}','Enter Your Email','auth-login-card','type="email"']:
            i=t.find(needle)
            print(needle,repr(t[max(0,i-180):i+220]))
print('Root files:',[p.name for p in root.iterdir() if p.is_file()])
PY
