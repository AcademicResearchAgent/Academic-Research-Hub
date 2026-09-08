set -euo pipefail
sudo docker image ls ghcr.io/open-webui/open-webui
sudo du -sh /var/lib/docker/tmp /var/lib/containerd/io.containerd.content.v1.content/ingest 2>/dev/null || true
free -h
df -h /
ps -eo pid,etime,pcpu,pmem,args | grep '[d]ocker pull'
