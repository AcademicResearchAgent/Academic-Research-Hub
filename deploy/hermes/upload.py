"""Upload a deployment artifact with SSH host verification enabled."""
import os
from pathlib import Path
import subprocess
import sys

source = Path(sys.argv[1]).resolve()
destination = sys.argv[2]
if not destination.startswith('/home/ubuntu/haudi-hermes/'):
    raise SystemExit('Destination must stay within the Hermes deployment directory.')
args = [r'C:\Windows\System32\OpenSSH\scp.exe', '-q',
        '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
        '-o', 'UserKnownHostsFile='+str(Path(__file__).resolve().parent/'known_hosts'),
        str(source), 'ubuntu@haudi-hermes-server:'+destination]
result = subprocess.run(args)
if result.returncode == 0:
    print('Uploaded:',source.name)
raise SystemExit(result.returncode)
