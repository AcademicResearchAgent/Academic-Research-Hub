set -euo pipefail
export PATH=/home/ubuntu/haudi-hermes/runtime/bin:/home/ubuntu/haudi-hermes/runtime/node/bin:$PATH
agent-browser --session haudi-research-copy-check click @e7
agent-browser --session haudi-research-copy-check wait --load networkidle
agent-browser --session haudi-research-copy-check snapshot
