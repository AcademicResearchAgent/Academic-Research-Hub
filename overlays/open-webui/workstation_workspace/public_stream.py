"""Public file receipts and non-stream collection without exposing host paths."""
import json
import re
from uuid import uuid4
from fastapi.responses import JSONResponse


def public_files(data):
    return [{'id': n['id'], 'name': n['name'], 'type': 'file', 'size': n['size'],
             'content_type': n['mime'], 'url': '/api/workstation/files/' + n['id'] + '/content',
             'workstation': {'project': data['project'], 'node': n['id'], 'version': n['version']}}
            for n in data.get('files', []) if n.get('kind') == 'file']


async def collect_response(iterator):
    text, reasoning, files = [], [], []
    error = None
    async for chunk in iterator:
        raw = chunk.decode().strip()
        if not raw.startswith('data:') or raw[5:].strip() == '[DONE]':
            continue
        data = json.loads(raw[5:].strip())
        if data.get('error'):
            error = data['error']
        for choice in data.get('choices', []):
            delta = choice.get('delta', {})
            text.append(delta.get('content') or '')
            reasoning.append(delta.get('reasoning_content') or '')
        if data.get('event', {}).get('type') == 'files':
            files.extend(data['event']['data']['files'])
    if error:
        return JSONResponse({'error': error}, status_code=502)
    return JSONResponse({'id': 'chatcmpl-' + uuid4().hex, 'object': 'chat.completion',
        'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': ''.join(text),
                     'reasoning_content': ''.join(reasoning), 'files': files}, 'finish_reason': 'stop'}]})
