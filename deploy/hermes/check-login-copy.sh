set -euo pipefail
export PATH=/home/ubuntu/haudi-hermes/runtime/bin:/home/ubuntu/haudi-hermes/runtime/node/bin:$PATH
agent-browser --session haudi-login-copy-check open http://127.0.0.1:9119/auth
agent-browser --session haudi-login-copy-check wait --load networkidle
agent-browser --session haudi-login-copy-check snapshot
