"""Observed recovery dialog + authenticated HTTP checks on synthetic preview data.

Prepare workspace-recovery-probe.json and open its project menu first. No LLM.
"""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import time

import httpx

ROOT = Path('/home/ubuntu/haudi-hermes')


def main():
    spec = importlib.util.spec_from_file_location('preview_browser', Path(__file__).with_name('verify-browser.py'))
    ui = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ui)
    manifest = json.loads((ROOT / 'workspace-recovery-probe.json').read_text())
    fixture = json.loads((ROOT / 'workspace-preview-fixtures.json').read_text())[0]
    ui.click('button "未完成文件"')
    ui.wait_for('heading "恢复未完成文件"')
    assert 'button "移入回收站"' not in ui.snapshot(), 'Project menu must close when opening its dialog'
    dialog = ui.browser('snapshot')
    assert '中断的输出可能不完整' in dialog and '已有文件不会被覆盖' in dialog
    ui.click('button "恢复文件"')
    ui.wait_for('button "恢复文件"', present=False)
    assert '没有待恢复的运行。' in ui.browser('snapshot')
    with httpx.Client(base_url='http://127.0.0.1:9120', timeout=30, trust_env=False) as client:
        response = client.post('/api/v1/auths/signin', json={k: fixture[k] for k in ('email', 'password')})
        response.raise_for_status()
        client.headers['Authorization'] = 'Bearer ' + response.json()['token']
        endpoint = '/api/workstation/projects/' + manifest['project']
        response = client.get(endpoint + '/files')
        response.raise_for_status()
        files = response.json()
        restored = next(file for file in files if file['kind'] == 'file' and file['run'] == manifest['run'])
        assert restored['path'].startswith('未完成文件-') and restored['source'] == 'agent-recovered'
        response = client.get('/api/workstation/files/' + restored['id'] + '/content')
        response.raise_for_status()
        assert response.content == b'# Synthetic partial\n'
        assert client.get('/api/workstation/files/' + manifest['original'] + '/content').content == b'# Synthetic original\n'
        assert len(client.get('/api/workstation/files/' + manifest['original'] + '/versions').json()) == 1
        response = client.post(endpoint + '/recoverable-runs/' + manifest['run'] + '/recover')
        response.raise_for_status()
        assert response.json()['files'] == []
        assert {file['id'] for file in client.get(endpoint + '/files').json()} == {file['id'] for file in files}
        assert client.get(endpoint + '/recoverable-runs').json() == []
    ui.click('button "关闭"')
    ui.click('tab "资源管理器"')
    folder = next(file for file in files if file['kind'] == 'directory' and file['id'] == restored['parent'])
    ui.wait_for('button "▸' + folder['name'] + '"')
    ui.click('button "▸' + folder['name'] + '"')
    # Observe the rendered title before using it to distinguish duplicate names.
    titles = json.loads(json.loads(ui.browser('eval', 'JSON.stringify(Array.from(document.querySelectorAll("button[title]")).filter(e=>e.getBoundingClientRect().height>0).map(e=>e.title))')))
    assert restored['path'] in titles
    ui.browser('click', 'button[title=' + json.dumps(restored['path'], ensure_ascii=False) + ']')
    ui.wait_for('heading "Synthetic partial"')
    assert 'draft.md' in titles
    ui.browser('click', 'button[title="draft.md"]')
    ui.wait_for('heading "Synthetic original"')
    ui.browser('reload')
    ui.wait_for('heading "Synthetic original"')
    for _ in range(20):
        body = ui.browser('snapshot')
        if '当前没有可用模型' in body:
            break
        time.sleep(0.3)
    assert '当前没有可用模型' in body and '已选择：科研助手' not in body
    report = {'verified_at': datetime.now(timezone.utc).isoformat(),
              'preview_image': json.loads((ROOT / 'workspace-preview.json').read_text())['image'],
              'ui_explicit_recovery': True, 'partial_in_separate_folder': True,
              'original_and_original_version_preserved': True, 'repeat_recovery_idempotent': True,
              'both_files_rendered': True, 'preview_survives_reload': True,
              'unconfigured_account_has_no_retired_default': True,
              'prepared_stopped_synthetic_copy': True, 'external_model_called': False}
    (ROOT / 'workspace-recovery-browser-verification.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
