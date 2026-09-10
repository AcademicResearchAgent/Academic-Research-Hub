"""Probe coalescing and credential races, without provider requests."""
import asyncio
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('availability',ROOT/'overlays/open-webui/workstation_models/availability.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class AvailabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_checks_share_request_and_cancellation_does_not_abort_it(self):
        checks=module.AvailabilityChecks(); gate=asyncio.Event(); count=0
        model={'provider':'fixture','id':'one','upstream_id':'one'}
        entry={'endpoint':'official','key':'test-key'}
        async def probe():
            nonlocal count
            count+=1
            await gate.wait()
            return ''
        first=asyncio.create_task(checks.check('alice',model,entry,probe))
        second=asyncio.create_task(checks.check('alice',model,entry,probe))
        await asyncio.sleep(0); await asyncio.sleep(0)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):await first
        gate.set()
        self.assertEqual((await second)['state'],'available')
        self.assertEqual(count,1)
        self.assertEqual(checks.snapshot('bob',model,entry)['state'],'checking')
        self.assertEqual(checks.snapshot('alice',model,{**entry,'endpoint':'other'})['state'],'checking')
    async def test_old_key_probe_cannot_validate_replacement_key(self):
        checks=module.AvailabilityChecks();gate=asyncio.Event()
        model={'provider':'fixture','id':'one','upstream_id':'one'}
        old={'endpoint':'official','key':'old'};new={**old,'key':'new'}
        async def probe():await gate.wait();return ''
        task=asyncio.create_task(checks.check('alice',model,old,probe))
        await asyncio.sleep(0)
        checks.invalidate('alice','fixture');gate.set();await task
        self.assertEqual(checks.snapshot('alice',model,new)['state'],'checking')

if __name__=='__main__':unittest.main()
