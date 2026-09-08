set -euo pipefail
export PATH=/home/ubuntu/haudi-hermes/runtime/bin:/home/ubuntu/haudi-hermes/runtime/node/bin:$PATH
agent-browser --session haudi-openwebui-smoke open http://127.0.0.1:18119
agent-browser --session haudi-openwebui-smoke wait --load networkidle
agent-browser --session haudi-openwebui-smoke snapshot
