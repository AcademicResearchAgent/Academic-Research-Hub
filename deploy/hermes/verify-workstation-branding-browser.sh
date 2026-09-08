set -euo pipefail
export PATH=/home/ubuntu/haudi-hermes/runtime/bin:/home/ubuntu/haudi-hermes/runtime/node/bin:$PATH
agent-browser --session haudi-branding-v3 open http://127.0.0.1:9119/auth
agent-browser --session haudi-branding-v3 wait --load networkidle
agent-browser --session haudi-branding-v3 snapshot
agent-browser --session haudi-branding-v3 eval 'JSON.stringify({title:document.title,hasVendorText:/open\s*webui/i.test(document.body.innerText),help:document.querySelector("#haudi-local-account-help")?.textContent})'
