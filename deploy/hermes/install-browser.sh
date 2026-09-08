set -euo pipefail
deploy_root=/home/ubuntu/haudi-hermes
export PATH="$deploy_root/runtime/node/bin:$PATH"
cd "$deploy_root/runtime"
npm install --prefix browser --no-audit --no-fund 'agent-browser@^0.26.0'
browser/node_modules/.bin/agent-browser install
browser/node_modules/.bin/agent-browser --version
browser/node_modules/.bin/agent-browser --session haudi-deploy-smoke open https://example.com
browser/node_modules/.bin/agent-browser --session haudi-deploy-smoke get title
browser/node_modules/.bin/agent-browser --session haudi-deploy-smoke close
