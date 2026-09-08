set -u
sudo journalctl -u haudi-hermes.service -n 65 --no-pager
ps -C uv,node,npm -o pid,ppid,etime,args
