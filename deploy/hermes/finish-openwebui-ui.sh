set -euo pipefail
export PATH=/home/ubuntu/haudi-hermes/runtime/bin:/home/ubuntu/haudi-hermes/runtime/node/bin:$PATH
agent-browser --session haudi-openwebui-smoke click @e6
agent-browser --session haudi-openwebui-smoke snapshot
agent-browser --session haudi-openwebui-smoke screenshot /home/ubuntu/haudi-hermes/logs/openwebui.png
agent-browser --session haudi-openwebui-smoke close
