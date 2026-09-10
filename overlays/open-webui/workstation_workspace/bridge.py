"""Account-checked chat routing to the private isolated execution broker."""
import asyncio
import os

import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from .router import bind_chat, import_native_file, store
from ..workstation_models.streaming import stream_agent_response
from .public_paths import PublicDeltaFilter


async def generate_isolated(form_data, user, model, endpoint, credential):
    metadata = form_data.get('metadata') or {}
    thread = metadata.get('chat_id')
    project = await bind_chat(user.id, thread)
    attachments = [*(form_data.get('files') or []), *(metadata.get('files') or [])]
    seen = set()
    for file in attachments:
        if not isinstance(file, dict):
            continue
        file_id = file.get('id')
        if file.get('type') in {'file', 'image'} and file_id and file_id not in seen:
            await import_native_file(user.id, project['id'], file_id, thread)
            seen.add(file_id)
    socket = os.environ.get('WORKSTATION_BROKER_SOCKET')
    if not socket:
        raise HTTPException(503, '独立科研运行器尚未配置。')
    # No caller-supplied project, provider endpoint, API credential or internal
    # session identifier is forwarded. These values came from verified stores.
    payload = {'owner': user.id, 'thread': thread, 'model_id': model['id'],
               'messages': form_data.get('messages', []),
               'runtime': {'model': model['upstream_id'], 'base_url': endpoint['url'], 'api_key': credential['key']}}
    client = httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=socket),
                              timeout=httpx.Timeout(1800, connect=10), trust_env=False)
    request = client.build_request('POST', 'http://workstation-broker/run', json=payload)
    if not form_data.get('stream'):
        # Use the identical isolated path for non-streaming clients. The adapter
        # collects public deltas; it never falls back to the shared legacy agent.
        from .public_stream import collect_response
        return await collect_response(stream_agent_response(client, request, public_filter=PublicDeltaFilter()))
    return StreamingResponse(stream_agent_response(client, request, public_filter=PublicDeltaFilter()), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
