set -euo pipefail
export PATH=/home/ubuntu/haudi-hermes/runtime/bin:/home/ubuntu/haudi-hermes/runtime/node/bin:$PATH
agent-browser --session haudi-webui-smoke open http://127.0.0.1:9119/chat
agent-browser --session haudi-webui-smoke wait --load networkidle
agent-browser --session haudi-webui-smoke snapshot
agent-browser --session haudi-webui-smoke screenshot /home/ubuntu/haudi-hermes/logs/dashboard.png
agent-browser --session haudi-webui-smoke close
