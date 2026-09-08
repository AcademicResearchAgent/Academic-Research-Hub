set -euo pipefail
ps -eo pid,etime,comm,%cpu,%mem --sort=-%cpu | head -n 8
df -h /home/ubuntu/haudi-hermes
curl --silent --fail http://127.0.0.1:9119/health
