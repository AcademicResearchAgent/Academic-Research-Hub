"""Behavioral checks for credential isolation and the cross-process runtime boundary."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from cryptography.fernet import InvalidToken

ROOT=Path(__file__).resolve().parents[1]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj)
    return obj
core=module('core',ROOT/'overlays/open-webui/workstation_models/core.py')
runtime=module('runtime',ROOT/'reference/hermes-agent/gateway/workstation_runtime.py')

class Credentials(unittest.TestCase):
    def setUp(self):
        (ROOT/'.build/tests').mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'.build/tests')
        self.path=Path(self.tmp.name)/'credentials.db'
        self.store=core.CredentialStore(self.path,'test-master-secret')
    def tearDown(self):self.tmp.cleanup()
    def test_user_provider_and_region_isolation(self):
        self.store.put('alice','qwen','cn','test-alice-secret','qwen-max')
        self.store.put('bob','qwen','cn','test-bob-secret','qwen-max')
        self.assertIsNone(self.store.get('alice','kimi'))
        self.assertEqual(self.store.get('bob','qwen')['key'],'test-bob-secret')
        self.store.put('alice','qwen','intl','test-alice-intl','qwen-flash')
        self.assertEqual(self.store.get('alice','qwen')['endpoint'],'intl')
        self.assertNotIn(b'test-alice-secret',self.path.read_bytes())
        self.assertNotIn(b'test-bob-secret',self.path.read_bytes())
        self.store.delete('alice','qwen')
        self.assertIsNone(self.store.get('alice','qwen'))
        self.assertEqual(self.store.get('bob','qwen')['key'],'test-bob-secret')
    def test_key_replacement_invalidates_previous_model_validation(self):
        self.store.put('alice','qwen','cn','test-key-original','max')
        self.store.mark_validated('alice','qwen','flash')
        self.assertEqual(set(self.store.get('alice','qwen')['validated']),{'max','flash'})
        self.store.put('alice','qwen','cn','test-key-replaced','max')
        self.assertEqual(self.store.get('alice','qwen')['validated'],['max'])
    def test_swapped_ciphertext_is_rejected(self):
        self.store.put('alice','qwen','cn','test-alice-key','max')
        self.store.put('bob','qwen','cn','test-bob-key','max')
        with self.store.connect() as db:
            db.execute("UPDATE credentials SET secret=(SELECT secret FROM credentials WHERE user_id='alice') WHERE user_id='bob'")
        with self.assertRaises(ValueError):self.store.get('bob','qwen')
    def test_encryption_requires_stable_secret(self):
        with self.assertRaises(RuntimeError):core.CredentialStore(self.path,'')
        self.store.put('alice','qwen','cn','test-alice-key','max')
        with self.assertRaises(InvalidToken):core.CredentialStore(self.path,'wrong-master').get('alice','qwen')

class Runtime(unittest.TestCase):
    def token(self,**changes):
        args=dict(model='deepseek-v4-flash',endpoint='https://api.deepseek.com/v1',key='test-personal-key',scope='scope-a')
        args.update(changes)
        return core.runtime_envelope('internal-secret',**args)
    def test_route_uses_personal_model_and_key(self):
        route=runtime.decode_route(self.token(),'internal-secret','scope-a')
        state={'provider':'global','api_key':'global-key','credential_pool':'global-pool'}
        model=runtime.apply_runtime(route,state)
        self.assertEqual(model,'deepseek-v4-flash')
        self.assertEqual(state['api_key'],'test-personal-key')
        self.assertIsNone(state['credential_pool'])
        self.assertEqual(state['base_url'],'https://api.deepseek.com/v1')
    def test_forged_expired_and_cross_session_routes_rejected(self):
        token=self.token()
        with self.assertRaises(InvalidToken):runtime.decode_route(token,'wrong-secret','scope-a')
        with self.assertRaises(ValueError):runtime.decode_route(token,'internal-secret','scope-b')
        with patch('time.time',return_value=1):expired=self.token()
        with self.assertRaises(InvalidToken):runtime.decode_route(expired,'internal-secret','scope-a')
        with self.assertRaises(ValueError):runtime.decode_route(self.token(endpoint='https://attacker.invalid/v1'),'internal-secret','scope-a')
        with self.assertRaises(ValueError):runtime.decode_route(self.token(model='unknown-model'),'internal-secret','scope-a')
    def test_scopes_differ_by_account_model_and_chat(self):
        a=core.session_scope('alice','qwen','chat','same prompt')
        self.assertNotEqual(a,core.session_scope('bob','qwen','chat','same prompt'))
        self.assertNotEqual(a,core.session_scope('alice','kimi','chat','same prompt'))
        self.assertNotEqual(a,core.session_scope('alice','qwen','other','same prompt'))
        self.assertEqual(a,core.session_scope('alice','qwen','chat','follow-up'))

if __name__=='__main__':unittest.main()
