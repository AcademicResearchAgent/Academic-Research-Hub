set -euo pipefail
export PATH=/home/ubuntu/haudi-hermes/runtime/bin:/home/ubuntu/haudi-hermes/runtime/node/bin:$PATH
agent-browser --session haudi-attachment-v4 open http://42.193.15.167:9119/auth
agent-browser --session haudi-attachment-v4 wait --load networkidle
agent-browser --session haudi-attachment-v4 snapshot
