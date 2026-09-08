set -u
echo DEPLOYMENT_PROGRESS
du -sh /home/ubuntu/haudi-hermes/* 2>/dev/null
ps -eo pid,comm,etime,rss --sort=-rss | head -10
free -h
systemctl is-active haudi-hermes.service 2>/dev/null || true
