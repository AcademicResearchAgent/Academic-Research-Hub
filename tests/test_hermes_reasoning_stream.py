"""Real aiohttp SSE writer with a gated agent producer; no provider calls."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.environ.get("WORKSTATION_HERMES_SOURCE", str(ROOT / "reference/hermes-agent")))


class HermesReasoningStream(unittest.IsolatedAsyncioTestCase):
    async def test_reasoning_reaches_client_before_agent_finishes(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        temporary_root = ROOT / '.build/streaming-tests'
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as profile:
            old_home = os.environ.get("HERMES_HOME")
            os.environ["HERMES_HOME"] = profile
            try:
                from gateway.platforms.api_server import ThreadSafeAsyncQueue
                from gateway.platforms.api_server_openai_routes import OpenAICompatRoutesMixin
                gate = asyncio.Event()

                class Adapter(OpenAICompatRoutesMixin):
                    async def _run_agent(self, stream_delta_callback, reasoning_callback, **kwargs):
                        await asyncio.to_thread(reasoning_callback, "公开的推理片段")
                        await gate.wait()
                        stream_delta_callback("最终回答")
                        return {"completed": True, "final_response": "最终回答"}, {}

                adapter = Adapter()

                async def handler(request):
                    queue = ThreadSafeAsyncQueue()
                    task, ref = adapter._spawn_stream_agent(queue, reasoning_callback=lambda text: queue.put_threadsafe(("__reasoning_delta__", text)))
                    return await adapter._write_sse_chat_completion(request, "fixture", "any-model", 0, queue, task, ref)

                app = web.Application()
                app.router.add_get("/stream", handler)
                async with TestClient(TestServer(app)) as client:
                    response = await client.get("/stream")
                    seen = None
                    while seen is None:
                        line = (await asyncio.wait_for(response.content.readline(), timeout=3)).decode()
                        if line.startswith("data:"):
                            item = json.loads(line[5:])
                            delta = item["choices"][0]["delta"]
                            seen = delta.get("reasoning_content")
                    self.assertEqual(seen, "公开的推理片段")
                    self.assertFalse(gate.is_set())
                    gate.set()
                    tail = (await response.read()).decode()
                    chunks = [json.loads(line[5:]) for line in tail.splitlines()
                              if line.startswith('data:') and line[5:].strip() != '[DONE]']
                    self.assertEqual(''.join(c['choices'][0]['delta'].get('content', '') for c in chunks), '最终回答')
                    self.assertIn("[DONE]", tail)
            finally:
                if old_home is None:
                    os.environ.pop("HERMES_HOME", None)
                else:
                    os.environ["HERMES_HOME"] = old_home


if __name__ == "__main__":
    unittest.main()
