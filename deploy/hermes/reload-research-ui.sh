set -euo pipefail
export PATH=/home/ubuntu/haudi-hermes/runtime/bin:/home/ubuntu/haudi-hermes/runtime/node/bin:$PATH
agent-browser --session haudi-research-copy-check open http://127.0.0.1:9119/
agent-browser --session haudi-research-copy-check wait --load networkidle
agent-browser --session haudi-research-copy-check snapshot
