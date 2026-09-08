"""Apply the reviewed model runtime with precondition hashes and service rollback."""
from datetime import datetime,timezone
import hashlib
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request

root=Path('/home/ubuntu/haudi-hermes')
release=Path((root/'openwebui/model-release-path.txt').read_text().strip())
assert release.resolve().is_relative_to(root/'model-releases')
baseline={
 'gateway/platforms/api_server.py':'cbd3fa1eac12e07e9788b91206ff33f8b7ffdcaee15753aabc45c42dd03ac05b',
 'gateway/platforms/api_server_openai_routes.py':'f460698815f2f89f10bbc22c58cc3595f8c20a27dae531c8c8bf2e04c61fc323',
}
files=[*baseline,'gateway/workstation_runtime.py','gateway/workstation_catalog.json']
for rel,digest in baseline.items():
    current=(root/'source'/rel).read_bytes()
    desired=(release/'reference/hermes-agent'/rel).read_bytes()
    assert hashlib.sha256(current).hexdigest()==digest or current==desired,'Unexpected server source modification: '+rel
backup=root/'model-runtime-backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
for rel in files:
    target=root/'source'/rel
    if target.exists():
        (backup/rel).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,backup/rel)
try:
    for rel in files:shutil.copy2(release/'reference/hermes-agent'/rel,root/'source'/rel)
    subprocess.run(['sudo','systemctl','restart','haudi-hermes-api.service'],check=True)
    for i in range(60):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8642/health',timeout=2) as response:
                if response.status==200:break
        except OSError:time.sleep(1)
    else:raise RuntimeError('Agent health check failed')
except Exception:
    for rel in files:
        if (backup/rel).exists():shutil.copy2(backup/rel,root/'source'/rel)
    subprocess.run(['sudo','systemctl','restart','haudi-hermes-api.service'],check=True)
    raise
print('Account-specific model runtime deployed; backup:',backup)
