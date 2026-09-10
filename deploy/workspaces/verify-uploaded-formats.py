"""Upload original formats over HTTP and read them through the real Hermes terminal.

Synthetic files only, private preview only, no model call. Uses the recorded
broker launcher and runtime image, then downloads the registered result over
the authenticated file API. This proves original bytes, not model perception.
"""
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import zipfile

import httpx
from PIL import Image

ROOT = Path('/home/ubuntu/haudi-hermes')
PROBE = ROOT / 'workspace-uploaded-formats-probe.json'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pdf():
    content = b'BT /F1 14 Tf 40 160 Td (SYNTHETIC_RESEARCH_PDF) Tj ET'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 320 200] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length ' + str(len(content)).encode() + b' >>\nstream\n' + content + b'\nendstream']
    data, offsets = b'%PDF-1.4\n', [0]
    for index, item in enumerate(objects, 1):
        offsets.append(len(data))
        data += str(index).encode() + b' 0 obj\n' + item + b'\nendobj\n'
    xref = len(data)
    data += b'xref\n0 6\n0000000000 65535 f \n'
    data += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    return data + b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n' + str(xref).encode() + b'\n%%EOF\n'


def main():
    assert os.geteuid() == 0
    os.umask(0o077)
    assert not PROBE.exists(), 'Inspect retained format verification before creating more data'
    runtime = json.loads((ROOT / 'workspace-broker-preview.json').read_text())
    preview = json.loads((ROOT / 'workspace-preview.json').read_text())
    source = ROOT / 'workspace-source-releases' / runtime['source_release']
    os.environ.update(WORKSTATION_WORKSPACE_ROOT=str(ROOT / 'workspace-preview-store'),
                      WORKSTATION_BROKER_SOCKET=str(ROOT / 'workspace-broker/broker.sock'),
                      WORKSTATION_RUNTIME_IMAGE=runtime['image'])
    sys.path.insert(0, str(source / 'overlays/open-webui'))
    broker = load('formats_broker', source / 'deploy/workspaces/broker.py')
    helper = load('formats_auth', Path(__file__).with_name('verify-history-browser.py'))
    account = json.loads((ROOT / 'workspace-preview-fixtures.json').read_text())[0]
    png, gif, archive = io.BytesIO(), io.BytesIO(), io.BytesIO()
    image = Image.new('RGB', (32, 24), '#2962ff')
    image.save(png, 'PNG')
    image.save(gif, 'GIF', save_all=True, append_images=[Image.new('RGB', (32, 24), '#ffffff')], duration=100, loop=0)
    with zipfile.ZipFile(archive, 'w') as package:
        package.writestr('paper/main.tex', '\\documentclass{article}\n\\begin{document}SYNTHETIC_ZIP\\end{document}\n')
        package.writestr('paper/references.bib', '@misc{synthetic,title={Synthetic reference}}\n')
    inputs = {'input.md': (b'# SYNTHETIC_MARKDOWN\n', 'text/markdown'),
              'paper.pdf': (pdf(), 'application/pdf'), 'figure.png': (png.getvalue(), 'image/png'),
              'animation.gif': (gif.getvalue(), 'image/gif'), 'paper.zip': (archive.getvalue(), 'application/zip')}
    manifest = {'phase': 'creating', 'source_release': runtime['source_release'],
                'preview_image': preview['image'], 'worker_image': runtime['image'], 'owner': account['id']}
    PROBE.write_text(json.dumps(manifest, indent=2))
    run = container = None
    with helper.client_for(account) as client:
        def call(method, path, **kwargs):
            response = client.request(method, '/api/workstation' + path, **kwargs)
            response.raise_for_status()
            return response
        try:
            first = call('POST', '/projects', json={'title': '多格式原件读取验收'}).json()
            project, thread = first['project']['id'], first['thread']
            second = call('POST', '/projects', json={'title': '同工作区第二对话', 'project': project}).json()['thread']
            manifest.update(project=project, thread=thread, second_thread=second)
            nodes = {}
            for name, (content, mime) in inputs.items():
                node = call('POST', '/projects/' + project + '/upload', files={'file': (name, content, mime)}).json()
                assert call('GET', '/files/' + node['id'] + '/content').content == content
                nodes[name] = node['id']
            assert len(call('GET', '/projects/' + project + '/files').json()) == len(inputs)
            assert call('POST', '/threads/' + thread + '/open').json()['last_thread'] == thread
            assert call('GET', '/threads/' + second + '/workspace').json()['last_thread'] == thread
            run = broker.begin_run(broker.STORE, account['id'], second)
            container, port = broker.start_container(run, secrets.token_urlsafe(32))
            manifest.update(phase='running', run=run['id'], nodes=nodes)
            PROBE.write_text(json.dumps(manifest, indent=2))
            with httpx.Client(timeout=2, trust_env=False) as worker:
                for _ in range(60):
                    try:
                        if worker.get(f'http://127.0.0.1:{port}/health').status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(1)
                else:
                    raise AssertionError('Synthetic format worker did not become healthy')
            checks = """import hashlib,json,subprocess,zipfile
from pathlib import Path
from PIL import Image
names=['input.md','paper.pdf','figure.png','animation.gif','paper.zip']
hashes={n:hashlib.sha256(Path(n).read_bytes()).hexdigest() for n in names}
assert 'SYNTHETIC_MARKDOWN' in Path('input.md').read_text()
assert 'SYNTHETIC_RESEARCH_PDF' in subprocess.check_output(['pdftotext','paper.pdf','-'],text=True)
with Image.open('figure.png') as image: assert image.size==(32,24);image.verify()
with Image.open('animation.gif') as image: assert image.n_frames==2
with zipfile.ZipFile('paper.zip') as z:
 assert sorted(z.namelist())==['paper/main.tex','paper/references.bib']
 assert b'SYNTHETIC_ZIP' in z.read('paper/main.tex')
assert not Path('paper').exists(), 'Uploaded ZIP must not be automatically extracted'
Path('format-read-results.json').write_text(json.dumps(hashes,sort_keys=True))
print('FORMATS_READ_OK')
"""
            code = 'import json,shlex\nfrom tools.terminal_tool import terminal_tool\n'
            code += 'result=json.loads(terminal_tool(command="/opt/venv/bin/python -c "+shlex.quote(' + repr(checks) + '),timeout=30,workdir="/workspace"))\n'
            code += 'assert result.get("exit_code")==0 and "FORMATS_READ_OK" in result.get("output",""), "Hermes terminal did not complete original-format checks"\nprint("HERMES_TERMINAL_FORMATS_OK")\n'
            response = subprocess.run(['docker', 'exec', '-i', '--user', '1000:1000', container, '/opt/venv/bin/python', '-'],
                                      input=code, text=True, capture_output=True, timeout=60)
            if response.returncode:
                print((response.stdout + response.stderr)[-2000:])  # Synthetic diagnostics only.
                raise AssertionError('Original-format terminal verification failed')
            assert 'HERMES_TERMINAL_FORMATS_OK' in response.stdout
            broker.stop_container(container)
            result = broker.finish_run(broker.STORE, account['id'], run['id'])
            assert len(result['files']) == 1 and not result['skipped']
            receipt = result['files'][0]
            expected = {name: hashlib.sha256(content).hexdigest() for name, (content, mime) in inputs.items()}
            assert call('GET', '/files/' + receipt['id'] + '/content').json() == expected
            for name, node in nodes.items():
                assert call('GET', '/files/' + node + '/content').content == inputs[name][0]
            assert call('GET', '/threads/' + second + '/workspace').json()['last_thread'] == thread
            assert call('POST', '/threads/' + second + '/open').json()['last_thread'] == second
            report = {'passed': True, 'verified_at': datetime.now(timezone.utc).isoformat(),
                      'source_release': runtime['source_release'], 'preview_image': preview['image'], 'worker_image': runtime['image'],
                      'authenticated_upload_and_original_download': list(inputs), 'real_hermes_terminal_read': True,
                      'pdf_text_extracted': True, 'png_decoded': True, 'gif_frames': 2, 'zip_contents_verified': True,
                      'zip_not_auto_extracted': True, 'all_original_hashes_unchanged': True,
                      'terminal_generated_result_registered_and_downloaded': True,
                      'second_thread_uses_same_workspace': True, 'read_only_binding_preserves_last_thread': True,
                      'explicit_open_updates_last_thread': True, 'external_model_called': False, 'production_changed': False}
            (ROOT / 'workspace-uploaded-formats-verification.json').write_text(json.dumps(report, indent=2))
            manifest['phase'] = 'complete'
            print(json.dumps(report), flush=True)
        finally:
            if container:
                broker.remove_container(container)
            if run:
                broker.finish_run(broker.STORE, account['id'], run['id'], interrupted=True)
                broker.discard_completed_copy(broker.STORE, account['id'], run['id'])
            PROBE.write_text(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
