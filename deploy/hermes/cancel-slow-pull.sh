set -euo pipefail
if [ "$(ps -p 85770 -o args=)" = 'docker pull ghcr.io/open-webui/open-webui:main-slim' ]; then
  sudo kill -INT 85770
  echo 'Stopped the deployment mirror download; using verified upload instead.'
fi
