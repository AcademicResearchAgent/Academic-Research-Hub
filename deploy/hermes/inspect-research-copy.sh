set -euo pipefail
sudo docker exec -i haudi-openwebui python - <<'PY'
from pathlib import Path
root=Path('/app/build')
needles=['有什么我能帮您的吗？','新对话','对话历史','研究','How can I help you today?']
for p in root.rglob('*'):
    if p.is_file() and p.suffix in {'.js','.json'}:
        t=p.read_text(errors='replace')
        if '有什么我能帮您的吗？' in t or ('translation' in p.name and '新对话' in t):
            print('Locale candidate:',p,'size',len(t))
            for needle in needles[:3]:
                i=t.find(needle)
                if i>=0: print(repr(t[max(0,i-80):i+100]))
for name in ['configs.py','models.py']:
    path=Path('/app/backend/open_webui/routers')/name
    lines=path.read_text().splitlines()
    for i,line in enumerate(lines):
        if any(x in line for x in ['suggestions','ModelForm','create_model','update_model','/create','/update','Banners','banner']):
            print(name,i+1,'\n'.join(lines[max(0,i-2):i+9]))
PY
if [ -f /home/ubuntu/haudi-hermes/state/SOUL.md ]; then
  cat /home/ubuntu/haudi-hermes/state/SOUL.md
else
  echo 'No profile SOUL.md override currently installed.'
fi
