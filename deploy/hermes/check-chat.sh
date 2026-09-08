set -euo pipefail
cd /home/ubuntu/haudi-hermes/source
export HERMES_HOME=/home/ubuntu/haudi-hermes/state
export PATH=/home/ubuntu/haudi-hermes/runtime/node/bin:/home/ubuntu/haudi-hermes/venv/bin:$PATH
python -u - <<'PY'
import asyncio, re, time
from pathlib import Path
import httpx
from websockets.asyncio.client import connect
html=httpx.get('http://127.0.0.1:9119/').text
token=re.search(r'__HERMES_SESSION_TOKEN__\s*=\s*["\']([^"\']+)',html).group(1)
async def main():
    output=''
    async with connect('ws://127.0.0.1:9119/api/pty?token='+token,origin='http://127.0.0.1:9119',open_timeout=30,max_size=8*1024*1024) as ws:
        print('Chat WebSocket: connected')
        await ws.send('\x1b[RESIZE:120;35]')
        deadline=time.monotonic()+40
        while time.monotonic()<deadline:
            try: data=await asyncio.wait_for(ws.recv(),timeout=3)
            except asyncio.TimeoutError:
                if len(output)>1000: break
                continue
            output+=data.decode(errors='replace') if isinstance(data,bytes) else data
            if 'Chat unavailable:' in output: raise RuntimeError(output[-1000:])
        clean=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',output)
        Path('/home/ubuntu/haudi-hermes/logs/chat-smoke.txt').write_text(clean)
        print('Terminal output bytes:',len(output))
        print('Terminal initialized:',len(output)>1000)
        readable=[line.strip() for line in clean.splitlines() if re.search('[A-Za-z]{3}',line)]
        print('Terminal text:', '\n'.join(readable[-25:]))
        if len(output)<1000: raise SystemExit('Terminal did not initialize')
asyncio.run(main())
PY
systemctl show haudi-hermes.service -p ActiveState -p MemoryCurrent
free -h
