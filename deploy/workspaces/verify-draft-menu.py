"""Check the final single-thread menu after the small presentation-only follow-up."""
import importlib.util
import json
import os
from pathlib import Path

import httpx

ROOT = Path('/home/ubuntu/haudi-hermes')


def main():
    os.umask(0o077)
    spec = importlib.util.spec_from_file_location('menu_browser', Path(__file__).with_name('verify-history-browser.py'))
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    ui = helper.ui
    account = json.loads((ROOT / 'workspace-preview-fixtures.json').read_text())[0]
    candidate = json.loads((ROOT / 'workspace-ui-candidate.json').read_text())
    preview = json.loads((ROOT / 'workspace-preview.json').read_text())
    assert preview['image'] == candidate['image']
    assert json.loads((ROOT / 'workspace-draft-preview-verification.json').read_text())['passed']
    with httpx.Client(base_url='http://127.0.0.1:9120', timeout=30, trust_env=False) as client:
        auth = client.post('/api/v1/auths/signin', json={k: account[k] for k in ('email', 'password')})
        auth.raise_for_status()
        client.headers['Authorization'] = 'Bearer ' + auth.json()['token']
        response = client.get('/api/workstation/projects')
        response.raise_for_status()
        project = next(p for p in response.json() if len(p['threads']) == 1)
    helper.browser('reload')
    if 'button "登录"' not in ui.snapshot():
        helper.logout()
    ui.wait_for('button "登录"')
    for label, key in (('textbox "本站科研账号', 'email'), ('textbox "密码', 'password')):
        helper.browser('fill', ui.control(label), account[key])
    ui.click('button "登录"')
    ui.wait_for('button "用户菜单"')
    if 'region "项目列表"' not in ui.snapshot():
        ui.click('button "展开侧边栏"')
    ui.wait_for('button "' + project['title'] + '"')
    ui.click('button "' + project['title'] + '"')
    ui.wait_for('tab "对话列表"')
    ui.click('tab "对话列表"')
    assert 'link "' + project['threads'][0]['title'] + '"' not in ui.snapshot()
    summaries = json.loads(json.loads(helper.browser('eval', 'JSON.stringify(Array.from(document.querySelectorAll(\'[aria-label="项目列表"] summary\')).map(e=>({label:e.getAttribute("aria-label"),visible:e.getBoundingClientRect().height>0})))')))
    label = '项目操作：' + project['title']
    assert any(item['label'] == label and item['visible'] for item in summaries)
    selector = 'summary[aria-label=' + json.dumps(label, ensure_ascii=False) + ']'
    helper.browser('click', selector)
    ui.wait_for('button "删除对话"')
    helper.browser('click', selector)
    helper.logout()
    result = {'passed': True, 'single_thread_row_hidden': True, 'delete_thread_available_in_project_menu': True,
              'image': preview['image'], 'mutated_project_data': False}
    (ROOT / 'workspace-draft-preview-menu-verification.json').write_text(json.dumps(result))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
