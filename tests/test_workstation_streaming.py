"""SSE behaviour checks, independent of a WebUI installation or provider key."""
import asyncio
import importlib.util
import json
from pathlib import Path
import unittest
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("workstation_streaming", ROOT / "overlays/open-webui/workstation_models/streaming.py")
streaming = importlib.util.module_from_spec(spec)
spec.loader.exec_module(streaming)


class Response:
    def __init__(self, frames, status=200):
        self.frames = frames
        self.status_code = status
        self.closed = False

    async def aiter_lines(self):
        for value in self.frames:
            if isinstance(value, asyncio.Event):
                await value.wait()
                continue
            for line in value.splitlines():
                yield line

    async def aclose(self):
        self.closed = True


class Client:
    def __init__(self, response, gate=None):
        self.response, self.gate = response, gate
        self.closed = self.sent = False

    async def send(self, request, stream):
        self.sent = True
        if self.gate:
            await self.gate.wait()
        return self.response

    async def aclose(self):
        self.closed = True


def chunk(delta, model="fixture", **extra):
    return streaming.frame({"model": model, "choices": [{"index": 0, "delta": delta, "finish_reason": None}], **extra}).decode()


def parse(value):
    raw = value.decode()[6:].strip()
    return raw if raw == "[DONE]" else json.loads(raw)


class StreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_interrupted_output_has_recovery_notice_without_successful_file_card(self):
        sys.path.insert(0, str(ROOT / 'reference/open-webui/backend'))
        response = Response([
            'event: workstation.files\ndata: ' + json.dumps({'project': 'owned-project', 'files': [],
                'status': 'interrupted', 'recovery_available': True}) + '\n\n',
            'data: [DONE]\n\n'])
        values = await self.collect(response)
        events = [value['event'] for value in values if isinstance(value, dict) and 'event' in value]
        self.assertFalse(any(event['type'] == 'files' for event in events))
        descriptions = [event['data']['description'] for event in events if event['type'] == 'status']
        self.assertTrue(any('未完成文件' in text and '原文件未被覆盖' in text for text in descriptions))
        self.assertEqual(descriptions[-1], '本次生成未完成')

    async def test_workspace_files_use_native_persistent_event_shape_and_hide_paths(self):
        sys.path.insert(0, str(ROOT / 'reference/open-webui/backend'))
        from open_webui.workstation_workspace.public_paths import PublicDeltaFilter
        files = {'project': 'owned-project', 'files': [{'id':'file-id','name':'综述.md','kind':'file',
                  'size':10,'mime':'text/markdown','version':1}], 'conflicts':[]}
        response = Response([
            'event: workstation.status\ndata: {"description":"正在准备工作区"}\n\n',
            chunk({'content':'文件 /home/ub'}), chunk({'content':'untu/haudi-hermes/private.md '}),
            'event: workstation.files\ndata: '+json.dumps(files)+'\n\n', 'data: [DONE]\n\n'])
        client = Client(response)
        values = [parse(v) async for v in streaming.stream_agent_response(client, None, public_filter=PublicDeltaFilter())]
        event = next(v['event'] for v in values if isinstance(v,dict) and v.get('event',{}).get('type')=='files')
        self.assertEqual(event['data']['files'][0]['workstation']['project'],'owned-project')
        self.assertEqual(event['data']['files'][0]['url'],'/api/workstation/files/file-id/content')
        text=''.join(c['delta'].get('content','') for v in values if isinstance(v,dict) for c in v.get('choices',[]))
        self.assertEqual(text,'文件 [内部路径] ')
        self.assertEqual(values[-1],'[DONE]')

    async def collect(self, response):
        client = Client(response)
        values = [parse(v) async for v in streaming.stream_agent_response(client, None)]
        self.assertTrue(client.closed)
        self.assertTrue(response.closed)
        return values

    async def test_status_precedes_upstream_headers_and_initial_close_cleans_up(self):
        client = Client(Response([]), asyncio.Event())
        gen = streaming.stream_agent_response(client, None)
        first = parse(await anext(gen))
        self.assertEqual(first["event"]["type"], "status")
        self.assertFalse(client.sent)
        await gen.aclose()
        self.assertTrue(client.closed)

    async def test_heartbeat_during_header_wait_does_not_cancel_request(self):
        gate = asyncio.Event()
        client = Client(Response([chunk({"content": "完成"}), "data: [DONE]\n\n"]), gate)
        gen = streaming.stream_agent_response(client, None, heartbeat_seconds=0.01)
        await anext(gen)
        tick = parse(await asyncio.wait_for(anext(gen), timeout=3))
        self.assertIn("已用时", tick["event"]["data"]["description"])
        gate.set()
        rest = [parse(v) async for v in gen]
        self.assertTrue(any(v.get("choices") for v in rest if isinstance(v, dict)))

    async def test_reasoning_fields_and_usage_preserved_for_any_model(self):
        for field in ("reasoning_content", "reasoning", "thinking"):
            with self.subTest(field=field):
                original = {field: "先检查约束。"}
                values = await self.collect(Response([chunk(original, model="arbitrary-model"),
                    chunk({"content": "结果。"}, usage={"total_tokens": 8}), "data: [DONE]\n\n"]))
                model_frames = [v for v in values if isinstance(v, dict) and v.get("choices")]
                self.assertEqual(model_frames[0]["choices"][0]["delta"], original)
                self.assertEqual(model_frames[1]["usage"], {"total_tokens": 8})
                self.assertEqual(values[-1], "[DONE]")

    async def test_tool_lifecycle_converted_to_status_without_fake_tool_calls(self):
        start = 'event: hermes.tool.progress\ndata: {"toolCallId":"a","status":"running","label":"do not expose arguments"}\n\n'
        stop = 'event: hermes.tool.progress\ndata: {"toolCallId":"a","status":"completed"}\n\n'
        values = await self.collect(Response([start, stop, "data: [DONE]\n\n"]))
        descriptions = [v["event"]["data"]["description"] for v in values if isinstance(v, dict) and "event" in v]
        receipts = [v['event']['data'] for v in values if isinstance(v, dict) and v.get('event', {}).get('data', {}).get('activity')]
        self.assertEqual([r['activity']['state'] for r in receipts], ['running', 'completed'])
        self.assertFalse(any("do not expose" in d for d in descriptions))
        self.assertFalse(any("tool_calls" in str(v) for v in values))

    async def test_activity_arrives_before_results_and_interruption_is_not_completion(self):
        gate = asyncio.Event()
        activity = {'title': '检索 · Crossref', 'detail': '检索式：Articraft', 'state': 'running'}
        start = 'event: hermes.tool.progress\ndata: ' + json.dumps({'toolCallId': 'paper', 'status': 'running', 'activity': activity}) + '\n\n'
        client = Client(Response([start, gate]))
        gen = streaming.stream_agent_response(client, None, heartbeat_seconds=.01)
        await anext(gen)
        await anext(gen)
        event = parse(await anext(gen))['event']['data']
        self.assertEqual(event['activity'], activity)
        self.assertFalse(gate.is_set())
        gate.set()
        rest = [parse(v) async for v in gen]
        receipts = [v['event']['data']['activity'] for v in rest if isinstance(v, dict) and v.get('event', {}).get('data', {}).get('activity')]
        self.assertEqual(receipts[-1]['state'], 'interrupted')

    async def test_no_reasoning_is_not_fabricated(self):
        values = await self.collect(Response([chunk({"content": "直接回答"}), "data: [DONE]\n\n"]))
        self.assertFalse(any("reasoning_content" in v["choices"][0]["delta"] for v in values if isinstance(v, dict) and v.get("choices")))

    async def test_upstream_http_error_is_visible_and_sanitized(self):
        values = await self.collect(Response([], status=401))
        self.assertTrue(any("error" in v for v in values if isinstance(v, dict)))
        self.assertEqual(values[-1], "[DONE]")

    async def test_truncated_stream_is_not_reported_as_success(self):
        values = await self.collect(Response([chunk({"reasoning_content": "partial"})]))
        self.assertTrue(any("error" in v for v in values if isinstance(v, dict)))
        self.assertEqual(values[-1], "[DONE]")

    async def test_cancel_during_upstream_read_closes_connection(self):
        client = Client(Response([asyncio.Event()]))
        gen = streaming.stream_agent_response(client, None)
        await anext(gen)
        await anext(gen)
        task = asyncio.create_task(anext(gen))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(client.closed)
        self.assertTrue(client.response.closed)


if __name__ == "__main__":
    unittest.main()
