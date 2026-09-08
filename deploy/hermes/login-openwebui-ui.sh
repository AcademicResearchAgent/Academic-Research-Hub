set -euo pipefail
export PATH=/home/ubuntu/haudi-hermes/runtime/bin:/home/ubuntu/haudi-hermes/runtime/node/bin:$PATH
/home/ubuntu/haudi-hermes/venv/bin/python - <<'PY'
import json, subprocess
from pathlib import Path
account=json.loads(Path('/home/ubuntu/haudi-hermes/openwebui/access.json').read_text())
command=['agent-browser','--session','haudi-openwebui-smoke']
for action in [['fill','@e2',account['email']],['fill','@e3',account['password']],['click','@e5']]:
    subprocess.run(command+action,check=True,capture_output=True)
print('Submitted administrator login in the server-local test browser.')
PY
agent-browser --session haudi-openwebui-smoke wait --load networkidle
agent-browser --session haudi-openwebui-smoke snapshot
