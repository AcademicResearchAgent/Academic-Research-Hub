"""Real model/MCP -> persisted chat cards -> PNG/GIF browser rendering.

Uses the public synthetic CFD sample embedded in the runtime. No user research
is loaded. Credentials remain on the server and are removed from the synthetic
account after execution. Existing started probes are never resent.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import time

from dotenv import dotenv_values
from PIL import Image

ROOT = Path('/home/ubuntu/haudi-hermes')
MANIFEST = ROOT / 'workspace-cfd-browser-probe.json'
MODEL = 'ws-deepseek-v4-pro'
ENDPOINT = 'https://api.deepseek.com/v1'
TITLE = 'CFD 产物网页交付验收'
PROMPT = ('这是合成样例的文件交付验收，不进行联网检索。请使用已配置的 CFD MCP 工具和公开内置样例 '
          '/opt/examples/cfd，依次执行 npy3d_inspect；npy3d_render_surface，参数 case="browser-check"、'
          'frame=0、channels="0"；npy3d_render_animation，参数 case="browser-check"、channel=0、'
          'max_frames=4、fps=2。必要时先搜索发现工具或加载 npy3d-visualization 技能。'
          '不要调用 run_full，不要生成报告，不要用终端重新绘图。完成后用一句中文交付真实生成的 PNG 和 GIF。')
spec = importlib.util.spec_from_file_location('cfd_browser_helper', Path(__file__).with_name('verify-history-browser.py'))
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
ui = helper.ui


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('prepare', 'execute', 'verify-existing'))
    args = parser.parse_args()
    assert os.geteuid() == 0
    os.umask(0o077)
    fixture = json.loads((ROOT / 'workspace-preview-fixtures.json').read_text())[0]
    with helper.client_for(fixture) as client:
        def call(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response
        if args.action == 'prepare':
            assert not MANIFEST.exists()
            catalog = call('GET', '/api/workstation/catalog').json()
            assert next(item for item in catalog['providers']['deepseek']['endpoints'] if item['id'] == 'official')['url'].rstrip('/') == ENDPOINT
            assert not catalog['credentials']['deepseek']['configured']
            created = call('POST', '/api/workstation/projects', json={'title': TITLE}).json()
            manifest = {'phase': 'prepared', 'owner': fixture['id'], 'project': created['project']['id'],
                        'thread': created['thread'], 'model': MODEL, 'endpoint': ENDPOINT,
                        'synthetic_only': True, 'prompt': PROMPT}
            MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
            print(json.dumps({'preflight': 'passed', 'external_endpoint': ENDPOINT,
                              'source': 'embedded synthetic CFD example', 'external_model_called': False}))
            return
        manifest = json.loads(MANIFEST.read_text())
        assert manifest['owner'] == fixture['id'] and manifest['endpoint'] == ENDPOINT and manifest['prompt'] == PROMPT
        added = False
        try:
            if args.action == 'execute':
                assert manifest['phase'] == 'prepared'
                assert call('GET', '/api/workstation/projects/' + manifest['project'] + '/files').json() == []
                chat = call('GET', '/api/v1/chats/' + manifest['thread']).json()
                assert not chat['chat']['history']['messages']
                catalog = call('GET', '/api/workstation/catalog').json()
                assert not catalog['credentials']['deepseek']['configured']
                assert next(item for item in catalog['providers']['deepseek']['endpoints'] if item['id'] == 'official')['url'].rstrip('/') == ENDPOINT
                key = dotenv_values(ROOT / 'state/.env').get('DEEPSEEK_API_KEY')
                assert key
                call('POST', '/api/workstation/credentials', json={'model_id': MODEL, 'endpoint_id': 'official', 'api_key': key})
                key = None
                added = True
                ui.browser('reload')
                ui.wait_for('button "' + TITLE + '"')
                ui.click('button "' + TITLE + '"')
                ui.wait_for('已选择：DeepSeek V4 Pro')
                ui.browser('fill', ui.control('generic "描述你的研究主题、科学问题或写作任务"'), PROMPT)
                manifest['phase'] = 'executing'
                MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
                ui.click('button "发送消息"')
                print(json.dumps({'phase': 'real_model_started', 'synthetic_only': True}), flush=True)
            else:
                assert manifest['phase'] == 'executing', 'Verify the existing run; do not resend it'
            deadline, last_notice = time.monotonic() + 360, 0
            cards = {}
            while time.monotonic() < deadline:
                chat = call('GET', '/api/v1/chats/' + manifest['thread']).json()
                for message in chat['chat']['history']['messages'].values():
                    if message.get('role') != 'assistant' or not message.get('done'):
                        continue
                    assert not message.get('error'), 'Synthetic CFD chat recorded an error'
                    for file in message.get('files', []):
                        suffix = Path(file.get('name', '')).suffix.lower()
                        if suffix in ('.png', '.gif') and file.get('workstation', {}).get('project') == manifest['project']:
                            cards[suffix] = file
                if len(cards) == 2:
                    break
                if time.monotonic() - last_notice > 20:
                    print(json.dumps({'phase': 'waiting_for_persisted_cfd_cards'}), flush=True)
                    last_notice = time.monotonic()
                time.sleep(1)
            assert len(cards) == 2, 'No completed PNG and GIF cards yet; inspect the existing run before resuming'
            activities = [entry.get('activity', {}) for message in chat['chat']['history']['messages'].values()
                          if message.get('role') == 'assistant' for entry in message.get('statusHistory', [])
                          if entry.get('action') == 'workstation_tool']
            required = ('npy3d_inspect', 'npy3d_render_surface', 'npy3d_render_animation')
            assert all(any(name in activity.get('title', '') and activity.get('state') == 'completed'
                           for activity in activities) for name in required), 'Missing actual completed CFD tool receipts'
            report = {'model': MODEL, 'endpoint': ENDPOINT, 'synthetic_only': True,
                      'preview_image': json.loads((ROOT / 'workspace-preview.json').read_text())['image'],
                      'completed_cfd_tool_receipts': list(required), 'artifacts': {}}
            for suffix, file in cards.items():
                content = call('GET', file['url']).content
                with Image.open(io.BytesIO(content)) as image:
                    size, frames = image.size, getattr(image, 'n_frames', 1)
                    image.verify()
                assert frames == (4 if suffix == '.gif' else 1)
                label = file['name'] + ' 打开文件'
                ui.wait_for(label)
                ui.click(label)
                ui.wait_for('heading "' + file['name'] + '"')
                for _ in range(30):
                    dimensions = json.loads(json.loads(ui.browser('eval', '''JSON.stringify((()=>{const image=document.querySelector('[aria-label="文件预览与编辑"] img');return image?[image.naturalWidth,image.naturalHeight]:null;})())''')))
                    if dimensions == list(size):
                        break
                    time.sleep(.5)
                assert dimensions == list(size)
                report['artifacts'][suffix] = {'actual_mcp_generated_file': True, 'native_chat_card_persisted': True,
                                               'authenticated_download_decoded': True, 'browser_card_rendered': True,
                                               'width': size[0], 'height': size[1], 'frames': frames}
            ui.browser('reload')
            ui.wait_for('heading "' + cards['.gif']['name'] + '"')
            for file in cards.values():
                ui.wait_for(file['name'] + ' 打开文件')
            report.update(passed=True, verified_at=datetime.now(timezone.utc).isoformat(),
                          cards_and_preview_survive_reload=True, production_changed=False)
            (ROOT / 'workspace-cfd-browser-verification.json').write_text(json.dumps(report, indent=2))
            manifest['phase'] = 'completed'
            MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
            print(json.dumps(report), flush=True)
        finally:
            if added:
                call('DELETE', '/api/workstation/credentials/deepseek')
                print('Temporary synthetic account credential removed.', flush=True)


if __name__ == '__main__':
    main()
