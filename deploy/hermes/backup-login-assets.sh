set -euo pipefail
root=/home/ubuntu/haudi-hermes/openwebui/login-customization/original
mkdir -p "$root/_app/immutable/nodes" "$root/_app/immutable/entry"
sudo docker cp haudi-openwebui:/app/build/index.html "$root/index.html"
sudo docker cp haudi-openwebui:/app/build/_app/immutable/nodes/52.D9R2snhE.js "$root/_app/immutable/nodes/52.D9R2snhE.js"
sudo docker cp haudi-openwebui:/app/build/_app/immutable/entry/app.DQIqq9im.js "$root/_app/immutable/entry/app.DQIqq9im.js"
sudo chown -R ubuntu:ubuntu "$root"
echo 'Original frontend assets retained for reproducible patching.'
