set -euo pipefail
export PATH=/home/ubuntu/haudi-hermes/runtime/bin:/home/ubuntu/haudi-hermes/runtime/node/bin:$PATH
python3 - <<'PY'
import json,subprocess
from pathlib import Path
account=json.loads(Path('/home/ubuntu/haudi-hermes/openwebui/access.json').read_text())
for action in [['fill','@e2',account['email']],['fill','@e3',account['password']],['click','@e5']]:
 subprocess.run(['agent-browser','--session','haudi-attachment-v4']+action,check=True,capture_output=True)
PY
agent-browser --session haudi-attachment-v4 wait --load networkidle
agent-browser --session haudi-attachment-v4 snapshot
