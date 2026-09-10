"""Browser rendering checks for the synthetic files prepared in the preview."""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import time

ROOT = Path('/home/ubuntu/haudi-hermes')
spec = importlib.util.spec_from_file_location('workspace_browser', Path(__file__).with_name('verify-browser.py'))
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)


def evaluate(expression):
    return json.loads(json.loads(ui.browser('eval', 'JSON.stringify(' + expression + ')')))


def image_ready():
    for _ in range(30):
        image = evaluate('(()=>{const i=document.querySelector(\'[aria-label="文件预览与编辑"] img\');return i?{width:i.naturalWidth,height:i.naturalHeight,source:i.currentSrc.startsWith("blob:")}:null;})()')
        if image and image['width'] > 0:
            return image
        time.sleep(.5)
    raise AssertionError('Image did not decode in the preview')


def main():
    checks = {}
    ui.click('button "▤预览图.png"')
    ui.wait_for('heading "预览图.png"')
    checks['png'] = image_ready()
    assert checks['png']['source'] and checks['png']['width'] == 320
    ui.click('button "放大图片"')
    ui.wait_for('button "125%"')
    checks['image_zoom'] = True
    ui.click('button "▤预览动画.gif"')
    ui.wait_for('heading "预览动画.gif"')
    checks['gif_decoded'] = image_ready()
    ui.click('button "▤预览数据.csv"')
    ui.wait_for('heading "预览数据.csv"')
    table = evaluate('(()=>{const e=document.querySelector(\'[aria-label="文件预览与编辑"] table\');return e?Array.from(e.rows,r=>Array.from(r.cells,c=>c.textContent)):null;})()')
    assert table == [['变量', '值', '说明'], ['A', '1', '合成,数据'], ['B', '2', '两行\n说明']], table
    checks['csv_quoted_cells_and_newlines'] = True
    ui.click('button "▤预览引用.md"')
    ui.wait_for('heading "合成预览材料"')
    checks['markdown_relative_image'] = image_ready()
    assert checks['markdown_relative_image']['source']
    assert evaluate('document.querySelectorAll(\'[aria-label="文件预览与编辑"] article script\').length') == 0
    ui.wait_for('link "阅读 PDF"')
    ui.click('link "阅读 PDF"')
    ui.wait_for('heading "预览论文.pdf"')
    for _ in range(40):
        canvas = evaluate('(()=>{const c=document.querySelector(\'[aria-label="文件预览与编辑"] canvas\');if(!c)return null;return {width:c.width,height:c.height};})()')
        if canvas and canvas['width'] > 0 and canvas['height'] > 0:
            break
        time.sleep(.5)
    assert canvas and canvas['width'] > 0, 'PDF did not render a page'
    checks['pdf_canvas'] = canvas
    checks['markdown_relative_file_link'] = True
    ui.browser('set', 'viewport', '390', '844')
    ui.wait_for('heading "预览论文.pdf"')
    bounds = evaluate('(()=>{const r=document.querySelector(\'[aria-label="文件预览与编辑"]\').getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,viewport:innerWidth};})()')
    assert bounds['x'] == 0 and bounds['width'] == 390 and bounds['height'] == 844, bounds
    checks['mobile_fullscreen'] = bounds
    ui.click('button "关闭文件预览"')
    ui.wait_for('region "文件预览与编辑"', present=False)
    ui.browser('set', 'viewport', '1280', '720')
    report = {'verified_at': datetime.now(timezone.utc).isoformat(), 'checks': checks,
              'scope': 'Synthetic uploaded files and responsive UI; actual CFD/LaTeX Agent delivery is separate.'}
    (ROOT / 'workspace-media-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
