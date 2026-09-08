set -euo pipefail
export PATH=/home/ubuntu/haudi-hermes/runtime/bin:/home/ubuntu/haudi-hermes/runtime/node/bin:$PATH
agent-browser --session haudi-attachment-v4 click @e21
agent-browser --session haudi-attachment-v4 snapshot
