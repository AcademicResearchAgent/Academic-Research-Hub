"""Create small synthetic files through the authenticated workspace upload API."""
import io
import json
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

ROOT = Path('/home/ubuntu/haudi-hermes')


def main():
    fixture = json.loads((ROOT / 'workspace-preview-fixtures.json').read_text())[0]
    image = Image.new('RGB', (320, 200), '#e8f0fe')
    draw = ImageDraw.Draw(image)
    draw.text((20, 20), 'Synthetic research preview', fill='#123456')
    draw.line([(20, 170), (70, 120), (130, 135), (190, 65), (280, 40)], fill='#2563eb', width=4)
    png, gif, pdf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    image.save(png, format='PNG')
    frame = image.copy()
    ImageDraw.Draw(frame).ellipse((240, 20, 260, 40), fill='red')
    image.save(gif, format='GIF', save_all=True, append_images=[frame], duration=300, loop=0)
    image.save(pdf, format='PDF', resolution=72)
    files = [('预览图.png', png.getvalue(), 'image/png'), ('预览动画.gif', gif.getvalue(), 'image/gif'),
             ('预览论文.pdf', pdf.getvalue(), 'application/pdf'),
             ('预览数据.csv', '变量,值,说明\nA,1,"合成,数据"\nB,2,"两行\n说明"\n'.encode(), 'text/csv'),
             ('预览引用.md', '# 合成预览材料\n\n![图](预览图.png)\n\n[阅读 PDF](预览论文.pdf)\n\n<script>throw new Error("UNSAFE_PREVIEW_SCRIPT")</script>\n'.encode(), 'text/markdown')]
    with httpx.Client(base_url='http://127.0.0.1:9120', timeout=30, trust_env=False) as client:
        response = client.post('/api/v1/auths/signin', json={k: fixture[k] for k in ('email', 'password')})
        response.raise_for_status()
        client.headers['Authorization'] = 'Bearer ' + response.json()['token']
        result = []
        for name, data, mime in files:
            response = client.post('/api/workstation/projects/' + fixture['project'] + '/upload', files={'file': (name, data, mime)})
            response.raise_for_status()
            result.append(response.json())
        (ROOT / 'workspace-preview-media.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps({'synthetic_files': [f['name'] for f in result], 'uploaded': len(result)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
