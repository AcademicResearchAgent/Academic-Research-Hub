"""HTTP behavior using isolated auth and mocked provider requests; no real credentials."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock,patch
import asyncio
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
pkgpath=ROOT/'reference/open-webui/backend/open_webui/workstation_models'
spec=importlib.util.spec_from_file_location('workstation_test',pkgpath/'__init__.py',submodule_search_locations=[str(pkgpath)])
pkg=importlib.util.module_from_spec(spec);sys.modules[spec.name]=pkg;spec.loader.exec_module(pkg)
async def auth():return types.SimpleNamespace(id='alice')
stub=types.ModuleType('open_webui.utils.auth');stub.get_verified_user=auth
previous_auth=sys.modules.get('open_webui.utils.auth')
sys.modules['open_webui.utils.auth']=stub
try:
    import workstation_test.router as api
finally:
    if previous_auth is None:sys.modules.pop('open_webui.utils.auth',None)
    else:sys.modules['open_webui.utils.auth']=previous_auth

class ModelAPI(unittest.TestCase):
    def setUp(self):
        (ROOT/'.build/tests').mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'.build/tests')
        api._store=api.CredentialStore(Path(self.tmp.name)/'credentials.db','test-secret')
        api._attempts.clear()
        self.app=FastAPI();self.app.include_router(api.router,prefix='/api/workstation')
        self.client=TestClient(self.app,base_url='https://workstation.test')
        self.key={'model_id':'ws-deepseek-v4-flash','endpoint_id':'official','api_key':'test-private-secret'}
    def tearDown(self):self.client.close();self.tmp.cleanup()
    def test_first_selection_and_validated_key_reuse(self):
        path='/api/workstation/models/ws-deepseek-v4-flash/activate'
        self.assertEqual(self.client.post(path).status_code,428)
        with patch.object(api,'validate',AsyncMock()) as validate:
            self.assertEqual(self.client.post('/api/workstation/credentials',json=self.key).status_code,200)
            self.assertEqual(self.client.post(path).status_code,200)
            validate.assert_awaited_once()
        response=self.client.get('/api/workstation/catalog')
        self.assertNotIn('test-private-secret',response.text)
        self.assertTrue(response.json()['credentials']['deepseek']['configured'])
        self.app.dependency_overrides[auth]=lambda:types.SimpleNamespace(id='bob')
        self.assertFalse(self.client.get('/api/workstation/catalog').json()['credentials']['deepseek']['configured'])
        self.assertEqual(self.client.post(path).status_code,428)
        self.client.delete('/api/workstation/credentials/deepseek')
        self.assertIsNotNone(api.store().get('alice','deepseek'))
    def test_invalid_key_not_persisted_and_does_not_overwrite(self):
        api.store().put('alice','deepseek','official','previous-valid-secret','ws-deepseek-v4-flash')
        with patch.object(api,'validate',AsyncMock(side_effect=HTTPException(400,'密钥无效'))):
            response=self.client.post('/api/workstation/credentials',json=self.key)
        self.assertEqual(response.status_code,400)
        self.assertEqual(api.store().get('alice','deepseek')['key'],'previous-valid-secret')
        self.assertNotIn(self.key['api_key'],response.text)
    def test_malformed_inputs_do_not_echo_key(self):
        for changes in ({'endpoint_id':'https://attacker.invalid'}, {'model_id':'other'}, {'api_key':{'secret':'sensitive-input'}}):
            response=self.client.post('/api/workstation/credentials',json={**self.key,**changes})
            self.assertIn(response.status_code,(400,404,422))
            self.assertNotIn('sensitive-input',response.text)
            self.assertNotIn('test-private-secret',response.text)
    def test_public_http_key_entry_rejected(self):
        with TestClient(self.app,base_url='http://public.test') as insecure:
            response=insecure.post('/api/workstation/credentials',json=self.key)
            self.assertEqual(response.status_code,400)
        self.assertIsNone(api.store().get('alice','deepseek'))
    def test_provider_error_is_sanitized(self):
        response=types.SimpleNamespace(status_code=401,text='Bearer test-private-secret')
        client=AsyncMock();client.post.return_value=response
        with patch.object(api.httpx,'AsyncClient') as cls:
            cls.return_value.__aenter__.return_value=client
            result=self.client.post('/api/workstation/credentials',json=self.key)
        self.assertEqual(result.status_code,400)
        self.assertNotIn(self.key['api_key'],result.text)
    def test_chat_bridge_uses_own_key_and_ignores_client_route(self):
        api.store().put('alice','deepseek','official','test-private-secret','ws-deepseek-v4-flash')
        client=AsyncMock()
        import httpx
        upstream=httpx.Response(200,json={'choices':[{'message':{'content':'OK'}}]})
        client.send.return_value=upstream
        from unittest.mock import Mock
        client.build_request=Mock(return_value='request')
        with patch.object(api.httpx,'AsyncClient',return_value=client),patch.dict('os.environ',{'WORKSTATION_AGENT_KEY':'internal-secret'}):
            result=asyncio.run(api.generate_chat(None,{'model':'ws-deepseek-v4-flash','messages':[{'role':'user','content':'hello'}],
                'stream':False,'metadata':{'chat_id':'chat-a'},'_workstation_runtime':'forged','api_key':'other-account-key'},types.SimpleNamespace(id='alice')))
        self.assertEqual(result.status_code,200)
        sent=client.build_request.call_args.kwargs
        self.assertNotIn('api_key',sent['json'])
        self.assertNotEqual(sent['json']['_workstation_runtime'],'forged')
        from workstation_test.core import cipher
        route=json.loads(cipher('internal-secret','/workstation-runtime/v1').decrypt(sent['json']['_workstation_runtime'].encode()))
        self.assertEqual(route['api_key'],'test-private-secret')
        self.assertEqual(route['model'],'deepseek-v4-flash')
        self.assertEqual(route['scope'],sent['headers']['X-Hermes-Session-Key'])

if __name__=='__main__':unittest.main()
