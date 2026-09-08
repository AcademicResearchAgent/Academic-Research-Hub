set -euo pipefail
sudo docker exec -i haudi-openwebui python - <<'PY'
from pathlib import Path
for filename, markers in {
    'models/models.py':['class ModelMeta','class ModelForm','class ModelParams'],
    'routers/configs.py':['class PromptSuggestion'],
    'routers/models.py':["@router.get('/model'"]
}.items():
    lines=(Path('/app/backend/open_webui')/filename).read_text().splitlines()
    for i,line in enumerate(lines):
        if any(marker in line for marker in markers):
            print(filename,'\n'.join(lines[i:i+30]))
locale=Path('/app/build/_app/immutable/chunks/CiT7BZod.js').read_text()
for value in ['新对话','对话历史','笔记','工作空间','知识','知识库','建议','有什么我能帮您的吗？','搜索对话','搜索笔记','新建笔记']:
    print('Exact locale value:',value,locale.count('"'+value+'"'))
PY
df -h /
