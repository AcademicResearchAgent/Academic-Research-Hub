"""Actual preview UI checks for large, unsupported and malformed synthetic files."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time

ROOT = Path('/home/ubuntu/haudi-hermes')
PROBE = ROOT / 'workspace-preview-fallbacks-probe.json'
DOWNLOAD = ROOT / 'workspace-preview-fallback-download.bin'
spec = importlib.util.spec_from_file_location('fallback_history_helper', Path(__file__).with_name('verify-history-browser.py'))
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
ui = helper.ui
TITLE = '预览降级验收'
INPUTS = {'unknown.bin': (b'\x00SYNTHETIC_UNKNOWN_FORMAT\xff', 'application/octet-stream'),
          'large.txt': (b'SYNTHETIC_LARGE_TEXT\n' + b'x' * (2 * 1024 * 1024), 'text/plain'),
          'broken.png': (b'SYNTHETIC_INVALID_IMAGE_BYTES', 'image/png'),
          'broken.pdf': (b'SYNTHETIC_INVALID_PDF_BYTES', 'application/pdf'),
          'untrusted.html': (b'<script>alert("SYNTHETIC_SCRIPT_MUST_NOT_RUN")</script>\n', 'text/html')}


def wait_text(text):
    for _ in range(30):
        if text in ui.browser('snapshot'):
            return
        time.sleep(.5)
    raise AssertionError('Expected fallback text not displayed: ' + text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('prepare', 'verify'))
    args = parser.parse_args()
    assert os.geteuid() == 0
    os.umask(0o077)
    account = json.loads((ROOT / 'workspace-preview-fixtures.json').read_text())[0]
    if args.action == 'prepare':
        assert not PROBE.exists()
        with helper.client_for(account) as client:
            response = client.post('/api/workstation/projects', json={'title': TITLE})
            response.raise_for_status()
            project = response.json()['project']['id']
            manifest = {'phase': 'preparing', 'project': project, 'owner': account['id'], 'files': {}}
            PROBE.write_text(json.dumps(manifest, indent=2))
            for name, (content, mime) in INPUTS.items():
                response = client.post('/api/workstation/projects/' + project + '/upload', files={'file': (name, content, mime)})
                response.raise_for_status()
                manifest['files'][name] = response.json()['id']
                PROBE.write_text(json.dumps(manifest, indent=2))
            manifest['phase'] = 'prepared'
            PROBE.write_text(json.dumps(manifest, indent=2))
        print(json.dumps({'synthetic_files_prepared': len(INPUTS), 'production_changed': False}))
        return
    manifest = json.loads(PROBE.read_text())
    assert manifest['phase'] == 'prepared' and manifest['owner'] == account['id']
    ui.browser('reload')
    ui.wait_for('button "' + TITLE + '"')
    ui.click('button "' + TITLE + '"')
    ui.click('tab "资源管理器"')
    results = {}
    for name, message in [('unknown.bin', '此格式暂不支持内嵌预览，请下载后查看。'),
                          ('large.txt', '文件较大，请下载后使用本地工具查看。'),
                          ('broken.png', '图片无法解析，请下载原文件检查格式。'),
                          ('broken.pdf', 'Failed to load PDF.')]:
        ui.click('button "▤' + name + '"')
        ui.wait_for('heading "' + name + '"')
        wait_text(message)
        assert not DOWNLOAD.exists()
        DOWNLOAD.touch(mode=0o600)
        os.chown(DOWNLOAD, 1000, 1000)
        try:
            ui.browser('download', ui.control('button "下载"'), str(DOWNLOAD))
            assert DOWNLOAD.read_bytes() == INPUTS[name][0]
        finally:
            DOWNLOAD.unlink(missing_ok=True)
        results[name] = {'fallback_shown': True, 'actual_browser_download_original': True}
    ui.click('button "▤untrusted.html"')
    ui.wait_for('textbox "文件源码编辑器"')
    data = json.loads(json.loads(ui.browser('eval', '''JSON.stringify((()=>{const panel=document.querySelector('[aria-label="文件预览与编辑"]');return {value:panel.querySelector('textarea').value,scriptCount:panel.querySelectorAll('script,iframe,object,embed').length};})())''')))
    assert data['value'] == INPUTS['untrusted.html'][0].decode() and data['scriptCount'] == 0
    report = {'passed': True, 'verified_at': datetime.now(timezone.utc).isoformat(),
              'preview_image': json.loads((ROOT / 'workspace-preview.json').read_text())['image'],
              'formats': results, 'html_displayed_as_inert_source': True,
              'model_called': False, 'production_changed': False}
    (ROOT / 'workspace-preview-fallbacks-verification.json').write_text(json.dumps(report, indent=2))
    manifest['phase'] = 'complete'
    PROBE.write_text(json.dumps(manifest, indent=2))
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
