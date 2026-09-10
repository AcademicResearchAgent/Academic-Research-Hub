"""Real primary + plugin auxiliary LLM test with an exact synthetic LaTeX ZIP."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import zipfile

import httpx
from dotenv import dotenv_values

ROOT = Path('/home/ubuntu/haudi-hermes')
ENDPOINT = 'https://api.deepseek.com/v1'
MODEL = 'ws-deepseek-v4-pro'
TEMPLATE = '\\documentclass{article}\n\\begin{document}\nTODO\n\\end{document}\n'
MATERIAL = 'Synthetic study of a fictional workflow. No experiments were conducted and no results are claimed.'
RECIPE_COMMAND = 'latexmk -pdf -bibtex -interaction=nonstopmode -halt-on-error main.tex'


def verify_archive(output):
    with zipfile.ZipFile(io.BytesIO(output)) as archive:
        generated = archive.read('main.tex').decode()
        assert MATERIAL in generated and 'TODO' not in generated
        assert '\\documentclass{article}' in generated
        assert archive.read('latex-paper-recipe.txt').decode().strip() == RECIPE_COMMAND
        metadata = json.loads(archive.read('.latex-paper.json'))
        assert metadata['recipe'] == 'pdflatex-bibtex'
        assert metadata['confirmed'] is True


def template_zip():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        info = zipfile.ZipInfo('main.tex', date_time=(1980, 1, 1, 0, 0, 0))
        info.external_attr = 0o100644 << 16
        archive.writestr(info, TEMPLATE.encode())
    return buffer.getvalue()


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute-verified', action='store_true')
    mode.add_argument('--verify-existing-output', action='store_true',
                      help='Only inspect the existing synthetic output; never repeat a model call')
    args = parser.parse_args()
    fixture = json.loads((ROOT / 'workspace-preview-fixtures.json').read_text())[0]
    manifest_path = ROOT / 'workspace-latex-runtime-probe.json'
    payload = template_zip()
    with httpx.Client(base_url='http://127.0.0.1:9120', timeout=900, trust_env=False) as client:
        response = client.post('/api/v1/auths/signin', json={k: fixture[k] for k in ('email', 'password')})
        response.raise_for_status()
        client.headers['Authorization'] = 'Bearer ' + response.json()['token']

        def call(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response

        catalog = call('GET', '/api/workstation/catalog').json()
        endpoint = next(item for item in catalog['providers']['deepseek']['endpoints'] if item['id'] == 'official')
        assert endpoint['url'].rstrip('/') == ENDPOINT
        assert not catalog['credentials']['deepseek']['configured']
        if not args.execute_verified and not args.verify_existing_output:
            assert not manifest_path.exists(), 'Inspect the existing synthetic LaTeX probe before replacing it'
            created = call('POST', '/api/workstation/projects', json={'title': 'LaTeX 插件合成验收'}).json()
            file = call('POST', '/api/workstation/projects/' + created['project']['id'] + '/upload',
                        files={'file': ('synthetic-template.zip', payload, 'application/zip')}).json()
            manifest = {'project': created['project']['id'], 'thread': created['thread'], 'input': file['id'],
                        'owner': fixture['id'], 'sha256': hashlib.sha256(payload).hexdigest(), 'endpoint': ENDPOINT}
            manifest_path.write_text(json.dumps(manifest, indent=2))
        else:
            manifest = json.loads(manifest_path.read_text())
        assert manifest['owner'] == fixture['id'] and manifest['endpoint'] == ENDPOINT
        files = call('GET', '/api/workstation/projects/' + manifest['project'] + '/files').json()
        uploaded = call('GET', '/api/workstation/files/' + manifest['input'] + '/content').content
        assert uploaded == payload and hashlib.sha256(uploaded).hexdigest() == manifest['sha256']
        if args.verify_existing_output:
            archives = [file for file in files if file['id'] != manifest['input']
                        and file['kind'] == 'file' and file['name'].endswith('.zip')]
            assert len(archives) == 1 and archives[0]['source'] == 'agent'
            output = call('GET', '/api/workstation/files/' + archives[0]['id'] + '/content').content
            verify_archive(output)
            report = {'verified_at': datetime.now(timezone.utc).isoformat(),
                      'preview_image': json.loads((ROOT / 'workspace-preview.json').read_text())['image'],
                      'synthetic_existing_output_only': True, 'zip_content_verified': True,
                      'output_sha256': hashlib.sha256(output).hexdigest(),
                      'recipe': 'pdflatex-bibtex', 'recipe_command': RECIPE_COMMAND,
                      'input_template_unchanged': True, 'authenticated_download': True,
                      'external_model_called_this_check': False, 'tex_not_compiled': True,
                      'stream_rechecked': False}
            (ROOT / 'workspace-latex-artifact-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps(report, ensure_ascii=False), flush=True)
            return
        assert len(files) == 1 and files[0]['id'] == manifest['input']
        if not args.execute_verified:
            print(json.dumps({'preflight': 'passed', 'project_files': 1, 'template_entry': 'main.tex',
                              'exact_template': TEMPLATE, 'exact_material': MATERIAL, 'sha256': manifest['sha256'],
                              'endpoint': ENDPOINT, 'api_key_read': False, 'external_model_called': False}), flush=True)
            return
        added = False
        receipts, activities, answer = [], {}, []
        try:
            key = dotenv_values(ROOT / 'state/.env').get('DEEPSEEK_API_KEY')
            assert key
            added = True
            call('POST', '/api/workstation/credentials', json={'model_id': MODEL, 'endpoint_id': 'official', 'api_key': key})
            key = None
            prompt = ('这是插件在隔离工作区中的合成验收，不联网检索、不执行 LaTeX 编译。唯一输入是 synthetic-template.zip。'
                      '请依次实际调用 latex_template_inspect、latex_project_generate、latex_project_validate、latex_project_confirm_package。'
                      '必须由 latex_project_generate 调用其辅助模型生成正文，不得改用终端或文件工具手写替代；插件失败时直接报告失败。'
                      '生成要求：保留 article 模板结构，只把 TODO 替换为下面这段已确认的英文合成材料，不加入作者、数据或引用：'
                      + MATERIAL + '。使用 pdflatex-bibtex 配方。本次测试已明确确认将这一合成工程打包为 ZIP，confirmed=true。'
                      '完成后交付生成的 ZIP，并用一句中文说明。')
            with client.stream('POST', '/api/chat/completions', json={'model': MODEL, 'stream': True,
                    'chat_id': manifest['thread'], 'messages': [{'role': 'user', 'content': prompt}]}) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line.startswith('data:'):
                        continue
                    raw = line[5:].strip()
                    if raw == '[DONE]':
                        break
                    data = json.loads(raw)
                    if data.get('error'):
                        raise AssertionError('Isolated synthetic LaTeX stream failed')
                    event = data.get('event', {})
                    if event.get('type') == 'files':
                        receipts.extend(event['data']['files'])
                    if event.get('type') == 'status':
                        activity = event.get('data', {}).get('activity', {})
                        if activity.get('title', '').startswith('latex_'):
                            activities[activity['title']] = activity
                            print(json.dumps({'tool': activity['title'], 'state': activity.get('state')}, ensure_ascii=False), flush=True)
                    for choice in data.get('choices', []):
                        answer.append(choice.get('delta', {}).get('content', ''))
            required = ('latex_template_inspect', 'latex_project_generate', 'latex_project_validate', 'latex_project_confirm_package')
            assert all(activities.get(name, {}).get('state') == 'completed' for name in required), json.dumps(activities, ensure_ascii=False)
            archives = [file for file in receipts if file['id'] != manifest['input'] and file['name'].endswith('.zip')]
            assert len(archives) == 1, 'Expected the real plugin ZIP file receipt'
            output = call('GET', archives[0]['url']).content
            verify_archive(output)
            assert call('GET', '/api/workstation/files/' + manifest['input'] + '/content').content == payload
            assert '/home/ubuntu/' not in ''.join(answer)
            report = {'verified_at': datetime.now(timezone.utc).isoformat(), 'model': MODEL, 'endpoint': ENDPOINT,
                      'preview_image': json.loads((ROOT / 'workspace-preview.json').read_text())['image'],
                      'worker_image': json.loads((ROOT / 'workspace-broker-preview.json').read_text())['image'],
                      'synthetic_only': True, 'real_plugin_auxiliary_generation': True,
                      'required_plugin_tools_completed': list(required), 'zip_content_verified': True,
                      'input_template_unchanged': True, 'native_zip_receipt': True, 'tex_not_compiled': True}
            (ROOT / 'workspace-latex-runtime-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps(report, ensure_ascii=False), flush=True)
        finally:
            if added:
                call('DELETE', '/api/workstation/credentials/deepseek')
                print('Temporary fixture credential removed.', flush=True)


if __name__ == '__main__':
    main()
