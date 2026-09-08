"""Download only the public, empty login-page screenshot for visual review."""
from pathlib import Path
import subprocess
from remote import OPTIONS
target=Path(__file__).resolve().parent/'.cache'/'login-copy.png'
target.parent.mkdir(exist_ok=True)
subprocess.run([
    r'C:\Windows\System32\OpenSSH\scp.exe','-q','-o','BatchMode=yes',
    '-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(target.parent.parent/'known_hosts'),
    'ubuntu@haudi-hermes-server:/home/ubuntu/haudi-hermes/logs/login-copy.png',str(target),
],check=True)
print('Empty login page screenshot saved for visual review.')
