"""Short-lived, account/credential/model-specific provider probe results."""
import asyncio
from collections import OrderedDict
import hashlib
import time


class AvailabilityChecks:
    def __init__(self):
        self.results = OrderedDict()
        self.pending = {}
        self.slots = asyncio.Semaphore(3)

    def identity(self, user_id, model, entry):
        fingerprint = hashlib.sha256((entry['endpoint'] + '\0' + entry['key']).encode()).hexdigest()
        return (user_id, model['provider'], model['id'], model['upstream_id'], fingerprint)

    def snapshot(self, user_id, model, entry):
        if not entry:
            return {'state': 'unconfigured', 'checked_at': None, 'detail': '请配置此厂商的 API Key。'}
        result = self.results.get(self.identity(user_id, model, entry))
        if result:
            ttl = 300 if result['state'] == 'available' else 60
            if time.time() - result['checked_at'] < ttl:
                return dict(result)
        return {'state': 'checking', 'checked_at': None, 'detail': '等待检测当前账号的模型访问权限。'}

    def remember(self, user_id, model, entry, state, detail=''):
        identity = self.identity(user_id, model, entry)
        result = {'state': state, 'checked_at': time.time(), 'detail': detail}
        self.results[identity] = result
        self.results.move_to_end(identity)
        while len(self.results) > 2048:
            self.results.popitem(last=False)
        return dict(result)

    def invalidate(self, user_id, provider):
        for identity in list(self.results):
            if identity[:2] == (user_id, provider):
                del self.results[identity]

    async def check(self, user_id, model, entry, probe):
        cached = self.snapshot(user_id, model, entry)
        if cached['state'] != 'checking':
            return cached
        identity = self.identity(user_id, model, entry)
        if identity not in self.pending:
            async def run():
                try:
                    async with self.slots:
                        # Probe returns only a sanitized failure description, never provider bodies.
                        detail = await probe()
                    return self.remember(user_id, model, entry, 'unavailable' if detail else 'available', detail)
                finally:
                    self.pending.pop(identity, None)
            self.pending[identity] = asyncio.create_task(run())
        return await asyncio.shield(self.pending[identity])
