set -euo pipefail
ps -u ubuntu -o pid,ppid,etimes,args | grep -F '/venv/bin/python -u -' | grep -v grep || true
