"""Open the remote Open WebUI + Hermes through a local SSH tunnel."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import urllib.request
import webbrowser
from remote import SSH, OPTIONS

parser = argparse.ArgumentParser()
parser.add_argument('--no-browser', action='store_true')
args = parser.parse_args()
base = Path(__file__).resolve().parent
url = 'http://127.0.0.1:9119'

def ready():
    try:
        with urllib.request.urlopen(url+'/health', timeout=2) as response:
            return response.status == 200 and response.headers.get_content_type() == 'application/json' and json.load(response).get('status') is True
    except Exception:
        return False

if not ready():
    log_path = base / 'tunnel.log'
    with log_path.open('ab') as log:
        proc = subprocess.Popen(
            [SSH, *OPTIONS, '-N', '-o', 'ExitOnForwardFailure=yes',
             '-L', '127.0.0.1:9119:127.0.0.1:9119', 'haudi-hermes-server'],
            stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    (base/'tunnel.pid').write_text(str(proc.pid), encoding='ascii')
    for attempt in range(20):
        if ready(): break
        if proc.poll() is not None:
            raise SystemExit('SSH tunnel failed. See '+str(log_path))
        time.sleep(0.5)
    else:
        proc.terminate()
        raise SystemExit('Open WebUI did not respond. See '+str(log_path))
print('科研智能体工作站：'+url)
if not args.no_browser:
    webbrowser.open(url)
