import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / 'overlays/open-webui/workstation_workspace/public_paths.py'
spec = importlib.util.spec_from_file_location('workspace_public_paths', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PublicPathTests(unittest.TestCase):
    def test_every_stream_split_hides_internal_paths_without_destroying_urls(self):
        text = '已生成 `/workspace/论文/main.tex`；缓存 /home/ubuntu/haudi-hermes/state/private.txt 。本地 file:///home/ubuntu/private.txt 。附件 /app/backend/data/uploads/input.pdf ，副本 file:///app/backend/data/uploads/input.pdf 。来源 https://example.org/opt/paper。'
        expected = '已生成 `论文/main.tex`；缓存 [内部路径] 。本地 [内部路径] 。附件 [内部路径] ，副本 [内部路径] 。来源 https://example.org/opt/paper。'
        for cut in range(len(text) + 1):
            stream = module.PublicDeltaFilter()
            result = ''
            for part in (text[:cut], text[cut:]):
                data = stream.transform({'choices': [{'index': 0, 'delta': {'content': part}}]})
                result += data['choices'][0]['delta']['content']
            tail = stream.flush()
            if tail:
                result += tail['choices'][0]['delta'].get('content', '')
            self.assertEqual(result, expected, f'split {cut}')

    def test_path_at_end_and_reasoning_are_also_filtered(self):
        stream = module.PublicDeltaFilter()
        result = ''
        for letter in '文件 /opt/hermes/config.yaml':
            data = stream.transform({'choices': [{'index': 0, 'delta': {'reasoning_content': letter}}]})
            result += data['choices'][0]['delta']['reasoning_content']
        result += stream.flush()['choices'][0]['delta']['reasoning_content']
        self.assertEqual(result, '文件 [内部路径]')
        self.assertEqual(module.clean_object({'detail': '/workspace/图表/output.png'}), {'detail': '图表/output.png'})


if __name__ == '__main__':
    unittest.main()
