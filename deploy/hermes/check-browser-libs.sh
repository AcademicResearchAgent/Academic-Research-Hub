set -u
ldd /home/ubuntu/.agent-browser/browsers/chrome-152.0.7977.82/chrome | grep 'not found' || true
apt-cache policy libatk1.0-0t64 libatk-bridge2.0-0t64 libatspi2.0-0t64 libasound2t64 libcups2t64 libgbm1 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2
