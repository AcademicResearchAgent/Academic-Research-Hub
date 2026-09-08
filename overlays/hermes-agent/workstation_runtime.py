"""Consume short-lived authenticated user/model routing envelopes from the local UI."""
import base64
import hashlib
import json
from pathlib import Path
from cryptography.fernet import Fernet

def decode_route(token,secret,scope):
    if not secret or not isinstance(token,str) or len(token)>16384:
        raise ValueError('Invalid workstation route')
    cipher=Fernet(base64.urlsafe_b64encode(hashlib.sha256((secret+'/workstation-runtime/v1').encode()).digest()))
    payload=json.loads(cipher.decrypt(token.encode(),ttl=120))
    if not scope or payload.get('scope')!=scope:raise ValueError('Session scope mismatch')
    catalog=json.loads((Path(__file__).parent/'workstation_catalog.json').read_text())
    model=next((m for m in catalog['models'] if m['upstream_id']==payload.get('model')),None)
    if not model:raise ValueError('Unknown workstation model')
    urls={e['url'] for e in catalog['providers'][model['provider']]['endpoints']}
    if payload.get('base_url') not in urls:raise ValueError('Endpoint does not match provider')
    key=payload.get('api_key')
    if not isinstance(key,str) or not 8<=len(key)<=4096 or any(c in key for c in '\r\n\x00'):
        raise ValueError('Invalid provider credential')
    return {'model':payload['model'],'base_url':payload['base_url'],'api_key':key,'provider':'custom','_workstation':True}

def apply_runtime(route,runtime):
    if not isinstance(route,dict) or route.get('_workstation') is not True:return None
    runtime.update({'provider':'custom','api_key':route['api_key'],'base_url':route['base_url'],
                    'api_mode':'chat_completions','credential_pool':None,'max_tokens':8192})
    return route['model']
