"""Exercise the observed synthetic fixture UI in the server's preview browser.

Run after verify-api.py --keep-fixtures and browser login. Fresh accessibility
snapshots resolve every control; no tokens or app state are injected in the page.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import time

import httpx

ROOT = Path('/home/ubuntu/haudi-hermes')
ENV = {**os.environ, 'PATH': str(ROOT / 'runtime/bin') + ':' + str(ROOT / 'runtime/node/bin') + ':' + os.environ['PATH']}


def browser(*args):
    return subprocess.check_output(['agent-browser', '--session', 'haudi-workspace-preview', *args],
                                   text=True, env=ENV, stderr=subprocess.DEVNULL)


def snapshot():
    return browser('snapshot', '-i')


def control(label):
    lines = [line for line in snapshot().splitlines() if label in line and 'ref=' in line]
    assert len(lines) == 1, 'Expected one visible control: ' + label
    return '@' + re.search(r'ref=(e\d+)', lines[0]).group(1)


def click(label):
    browser('scrollintoview', control(label))
    browser('click', control(label))


def wait_for(label, present=True):
    for _ in range(30):
        current = snapshot()
        if (label in current) == present:
            return current
        time.sleep(.5)
    raise AssertionError('Page did not reach expected state: ' + label)


def main():
    fixture = json.loads((ROOT / 'workspace-preview-fixtures.json').read_text())[0]
    wait_for('heading "main.md"')
    if 'textbox "文件源码编辑器"' not in snapshot():
        click('button "源码／编辑"')
    text = '# 浏览器编辑验收\n\n来自真实页面的保存。\n\n' + datetime.now(timezone.utc).isoformat() + '\n'
    browser('fill', control('textbox "文件源码编辑器"'), text)
    wait_for('button "保存" [ref=')
    click('button "独立项目"')
    wait_for('region "文件预览与编辑"', present=False)
    click('button "固定课题名"')
    wait_for('heading "main.md"')
    if 'textbox "文件源码编辑器"' not in snapshot():
        click('button "源码／编辑"')
    assert '来自真实页面的保存。' in wait_for('textbox "文件源码编辑器"')
    click('button "保存"')
    wait_for('button "保存" [disabled,')
    with httpx.Client(base_url='http://127.0.0.1:9120', timeout=30, trust_env=False) as client:
        response = client.post('/api/v1/auths/signin', json={k: fixture[k] for k in ('email', 'password')})
        response.raise_for_status()
        client.headers['Authorization'] = 'Bearer ' + response.json()['token']
        response = client.get('/api/workstation/files/' + fixture['file'] + '/content')
        response.raise_for_status()
        assert response.text == text
        versions = client.get('/api/workstation/files/' + fixture['file'] + '/versions').json()
        assert len(versions) >= 3
    click('button "预览"')
    wait_for('heading "浏览器编辑验收"')
    # DOM geometry validates the actual displayed panel and document overflow.
    measured = browser('eval', '''JSON.stringify((()=>{const r=document.querySelector('[aria-label="文件预览与编辑"]').getBoundingClientRect();return {viewport:innerWidth,document:document.documentElement.scrollWidth,x:r.x,width:r.width,right:r.right};})())''')
    bounds = json.loads(json.loads(measured))
    assert bounds['width'] >= 300 and bounds['right'] <= bounds['viewport'] + 1
    assert bounds['document'] <= bounds['viewport'] + 1
    browser('screenshot', str(ROOT / 'workspace-preview-markdown-fixed.png'))
    report = {'verified_at': datetime.now(timezone.utc).isoformat(), 'desktop_bounds': bounds,
              'markdown_render': True, 'source_editor_save': True,
              'draft_survives_project_switch': True, 'other_project_hides_preview': True,
              'saved_content_verified_over_http': True, 'version_count': len(versions),
              'scope': 'Synthetic Markdown fixture and desktop layout; PDF/image/mobile and Agent delivery need separate checks.'}
    (ROOT / 'workspace-browser-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
