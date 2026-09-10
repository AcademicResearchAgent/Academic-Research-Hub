"""Check real preview responses to renamed and moved synthetic files."""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import time

import httpx

ROOT = Path('/home/ubuntu/haudi-hermes')
spec = importlib.util.spec_from_file_location('ui', Path(__file__).with_name('verify-browser.py'))
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)


def image_loaded():
    result = ui.browser('eval', 'JSON.stringify((()=>{const i=document.querySelector(\'[aria-label="文件预览与编辑"] article img\');return !!i&&i.currentSrc.startsWith("blob:")&&i.naturalWidth===320;})())')
    return json.loads(json.loads(result))


def main():
    fixture = json.loads((ROOT / 'workspace-preview-fixtures.json').read_text())[0]
    media = {f['name']: f for f in json.loads((ROOT / 'workspace-preview-media.json').read_text())}
    markdown, image = media['预览引用.md'], media['预览图.png']
    ui.click('button "▤预览引用.md"')
    ui.wait_for('heading "合成预览材料"')
    with httpx.Client(base_url='http://127.0.0.1:9120', timeout=30, trust_env=False) as client:
        response = client.post('/api/v1/auths/signin', json={k: fixture[k] for k in ('email', 'password')})
        response.raise_for_status()
        client.headers['Authorization'] = 'Bearer ' + response.json()['token']
        folder = client.post('/api/workstation/projects/' + fixture['project'] + '/files', json={'name': '相对路径验收', 'directory': True}).json()
        assert folder.get('id')

        def move(file, name, parent=''):
            client.patch('/api/workstation/files/' + file['id'], json={'name': name, 'parent': parent}).raise_for_status()

        try:
            move(markdown, '预览引用.txt')
            ui.wait_for('heading "预览引用.txt"')
            ui.wait_for('textbox "文件源码编辑器"')
            response = client.get('/api/workstation/files/' + markdown['id'] + '/content')
            assert response.headers['content-type'].startswith('text/plain')
            move(markdown, '预览引用.md', folder['id'])
            ui.wait_for('heading "合成预览材料"')
            # The same file is still open. Relative images must now resolve
            # against its new directory, where the old root image is absent.
            for _ in range(30):
                if not image_loaded():
                    break
                time.sleep(.5)
            assert not image_loaded(), 'Moving Markdown kept its previous relative image'
            move(image, image['name'], folder['id'])
            for _ in range(30):
                if image_loaded():
                    break
                time.sleep(.5)
            assert image_loaded(), 'Moving the image beside Markdown did not refresh the rendered link'
            report = {'verified_at': datetime.now(timezone.utc).isoformat(),
                      'same_file_id_after_rename': True, 'renamed_content_type_updated': True,
                      'preview_changed_to_source_for_txt': True, 'markdown_move_invalidated_old_image': True,
                      'image_move_refreshed_relative_link': True, 'synthetic_files_only': True}
            (ROOT / 'workspace-file-move-verification.json').write_text(json.dumps(report, indent=2))
            print(json.dumps(report), flush=True)
        finally:
            move(markdown, markdown['name'], markdown['parent'])
            move(image, image['name'], image['parent'])
            client.delete('/api/workstation/files/' + folder['id']).raise_for_status()


if __name__ == '__main__':
    main()
