import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('activity', Path(__file__).resolve().parents[1] / 'overlays/hermes-agent/workstation_activity.py')
activity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(activity)


class ActivityTests(unittest.TestCase):
    def test_nested_mcp_receipt_has_actual_titles_and_evidence(self):
        tracker = activity.ActivityTracker()
        start = tracker.start('1', 'mcp__research_papers__europepmc_search', {'query': 'CRISPR'})
        self.assertIn('Europe PMC', start['activity']['title'])
        self.assertIn('CRISPR', start['activity']['detail'])
        data = {'records': [{'title': 'A real returned title', 'url': 'https://doi.org/10.1/x', 'evidence_level': 'abstract'}]}
        result = json.dumps({'result': {'content': [{'type': 'text', 'text': json.dumps(data)}]}})
        end = tracker.complete('1', 'mcp__research_papers__europepmc_search', result)['activity']
        self.assertEqual(end['items'][0]['title'], data['records'][0]['title'])
        self.assertIn('含摘要', end['items'][0]['note'])
        self.assertEqual(tracker.calls, {})

    def test_web_search_and_partial_extract(self):
        start = activity.start_activity('web_search', {'query': 'Articraft'})
        end = activity.finish_activity(start, 'web_search', {'success': True, 'data': {'web': [{'title': 'Articraft', 'url': 'https://arxiv.org/abs/1234.5'}]}}, 2)
        self.assertEqual(end['items'][0]['title'], 'Articraft')
        end = activity.finish_activity({}, 'web_extract', {'results': [{'url': 'https://a.org', 'content': 'text'}, {'url': 'https://b.org', 'error': 'credential SECRET'}]}, 2)
        self.assertEqual(end['state'], 'partial')
        self.assertNotIn('SECRET', str(end))
        self.assertIn('1/2', end['summary'])

    def test_empty_failed_unstructured_and_fulltext_distinct(self):
        self.assertIn('未命中', activity.finish_activity({}, 'x', {'records': []}, 0)['summary'])
        for result in [{'isError': True}, {'success': False}, {'error': 'sk-private'}, 'Error: sk-secret', {'exit_code': 1}]:
            self.assertEqual(activity.finish_activity({}, 'x', result, 0)['state'], 'failed')
        self.assertIn('未提供', activity.finish_activity({}, 'x', 'opaque text', 0)['summary'])
        end = activity.finish_activity({}, 'x', {'evidence_level': 'fulltext_excerpt', 'text': 'abc', 'offset': 100, 'total_chars': 500}, 0)
        self.assertIn('3 字符', end['summary'])
        self.assertIn('不代表', end['items'][0]['note'])

    def test_private_fields_are_not_forwarded(self):
        start = activity.start_activity('terminal', {'command': 'curl -H "Authorization: Bearer TOPSECRET" https://x.org'})
        self.assertEqual(start['detail'], '程序：curl')
        unknown = activity.start_activity('custom_plugin', {'api_key': 'TOPSECRET', 'text': 'PRIVATE'})
        self.assertNotIn('PRIVATE', str(unknown))
        url = activity.safe_url('https://user:pass@x.org/paper?api_key=TOPSECRET#token')
        self.assertEqual(url, 'https://x.org/paper')
        self.assertNotIn('TOPSECRET', activity.clean('query token=TOPSECRET'))

    def test_parallel_calls_are_independent(self):
        tracker = activity.ActivityTracker()
        tracker.start('1', 'web_search', {'query': 'first'})
        tracker.start('2', 'web_search', {'query': 'second'})
        end = tracker.complete('2', 'web_search', {})
        self.assertIn('second', end['activity']['detail'])
        self.assertEqual(list(tracker.calls), ['1'])


if __name__ == '__main__':
    unittest.main()
