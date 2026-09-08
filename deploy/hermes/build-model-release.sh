set -euo pipefail
root=/home/ubuntu/haudi-hermes
release="$root/model-releases/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$release"
tar -xzf "$root/model-release.tar.gz" -C "$release"
cd "$release"
cat > Dockerfile <<'EOF'
FROM haudi-openwebui:0.11.3-research-v4
COPY reference/open-webui/build/ /app/build/
COPY reference/open-webui/backend/open_webui/ /app/backend/open_webui/
EOF
sudo docker build -t haudi-openwebui:0.11.3-research-v5 .
sudo docker run --rm --network none --entrypoint python --mount "type=bind,src=$release,dst=/work" -w /work \
  haudi-openwebui:0.11.3-research-v5 -m unittest discover -s tests -p 'test_workstation*.py' -v
printf '%s\n' "$release" > "$root/openwebui/model-release-path.txt"
echo 'Model release built and isolated backend tests passed. Live services unchanged.'
