set -euo pipefail
export PATH=/home/ubuntu/haudi-hermes/runtime/bin:/home/ubuntu/haudi-hermes/runtime/node/bin:$PATH
python3 - <<'PY'
import json,subprocess
from pathlib import Path
account=json.loads(Path('/home/ubuntu/haudi-hermes/openwebui/access.json').read_text())
command=['agent-browser','--session','haudi-branding-v3']
for action in [['fill','@e2',account['email']],['fill','@e3',account['password']],['click','@e5']]:
    subprocess.run(command+action,check=True,capture_output=True)
print('Existing account submitted through login page.')
PY
agent-browser --session haudi-branding-v3 wait --load networkidle
agent-browser --session haudi-branding-v3 eval 'JSON.stringify({title:document.title,path:location.pathname,hasVendorText:/open\s*webui/i.test(document.body.innerText),hasAssistant:document.body.innerText.includes("科研助手"),hasResearchSuggestions:document.body.innerText.includes("跨库文献检索")})'
agent-browser --session haudi-branding-v3 close
