"""Authenticated catalog/key APIs and the account-specific Agent bridge."""
import asyncio
from collections import defaultdict,deque
import json
import os
from pathlib import Path
import time
import httpx
from fastapi import APIRouter,Depends,HTTPException,Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse,StreamingResponse
from pydantic import BaseModel,Field,SecretStr
from open_webui.utils.auth import get_verified_user
from .core import CredentialStore,runtime_envelope,session_scope

class PrivateValidationRoute(APIRoute):
    def get_route_handler(self):
        handler=super().get_route_handler()
        async def guarded(request):
            try:return await handler(request)
            except RequestValidationError:
                return JSONResponse({'detail':'请检查模型、接入区域和 API Key 的格式。'},status_code=422)
        return guarded

router=APIRouter(route_class=PrivateValidationRoute)
CATALOG=json.loads((Path(__file__).parent/'catalog.json').read_text())
MODELS={m['id']:m for m in CATALOG['models']}
_store=None
_attempts=defaultdict(deque)

def store():
    global _store
    if _store is None:
        _store=CredentialStore(Path(os.environ.get('DATA_DIR','/app/backend/data'))/'workstation-credentials.db',os.environ.get('WEBUI_SECRET_KEY',''))
    return _store

def model_info(model_id):
    if model_id not in MODELS:raise HTTPException(404,'未找到该科研模型，请刷新模型目录。')
    return MODELS[model_id]

def endpoint_info(provider,endpoint_id):
    endpoints=CATALOG['providers'][provider]['endpoints']
    entry=next((e for e in endpoints if e['id']==endpoint_id),None)
    if not entry:raise HTTPException(400,'请选择该厂商支持的接入区域。')
    return entry

def secure_key_entry(request):
    if request.url.scheme!='https' and request.url.hostname not in ('localhost','127.0.0.1','::1'):
        raise HTTPException(400,'API Key 请通过 HTTPS 或 localhost 安全入口配置。')

def rate_limit(user_id):
    now=time.monotonic();items=_attempts[user_id]
    while items and now-items[0]>60:items.popleft()
    if len(items)>=6:raise HTTPException(429,'验证次数较多，请稍后重试。')
    items.append(now)

async def validate(model,endpoint,key):
    payload={'model':model['upstream_id'],'messages':[{'role':'user','content':'Reply OK.'}],'max_tokens':16,'stream':False}
    if model['provider']=='qwen':payload['enable_thinking']=False
    if model['provider']=='deepseek':payload['thinking']={'type':'disabled'}
    if model['upstream_id']=='kimi-k3':payload['reasoning_effort']='low'
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(40,connect=10),follow_redirects=False,trust_env=False) as c:
            response=await c.post(endpoint['url']+'/chat/completions',headers={'Authorization':'Bearer '+key},json=payload)
    except httpx.HTTPError:
        raise HTTPException(502,'连接厂商超时或失败，请检查接入区域后重试。') from None
    if response.status_code in (401,403):raise HTTPException(400,'API Key 无效或无访问权限，请检查密钥和接入区域。')
    if response.status_code in (402,429):raise HTTPException(400,'该账号余额、配额或请求频率受限，请在厂商控制台检查。')
    if response.status_code==404:raise HTTPException(400,'该接入区域尚不可用此模型，请开通模型权限或选择其他模型。')
    if response.status_code!=200:raise HTTPException(502,'厂商未接受验证请求，请确认该模型的访问权限并稍后重试。')
    try:
        result=response.json()
        if not isinstance(result.get('choices'),list) or not result['choices']:raise ValueError()
    except (ValueError,AttributeError):raise HTTPException(502,'厂商返回了无法识别的验证结果。') from None

@router.get('/catalog')
async def catalog(user=Depends(get_verified_user)):
    states={}
    for provider in CATALOG['providers']:
        entry=await asyncio.to_thread(store().get,user.id,provider)
        states[provider]={'configured':bool(entry),'endpoint_id':entry['endpoint'] if entry else None}
    return {**CATALOG,'credentials':states}

class KeyForm(BaseModel):
    model_id:str
    endpoint_id:str
    api_key:SecretStr=Field(min_length=8,max_length=4096)

@router.post('/credentials')
async def save_key(form:KeyForm,request:Request,user=Depends(get_verified_user)):
    secure_key_entry(request);rate_limit(user.id)
    model=model_info(form.model_id);endpoint=endpoint_info(model['provider'],form.endpoint_id)
    key=form.api_key.get_secret_value().strip()
    if any(c in key for c in '\r\n\x00'):raise HTTPException(400,'API Key 格式不正确。')
    await validate(model,endpoint,key)
    await asyncio.to_thread(store().put,user.id,model['provider'],form.endpoint_id,key,model['id'])
    return {'configured':True,'provider':model['provider'],'endpoint_id':form.endpoint_id}

@router.post('/models/{model_id}/activate')
async def activate(model_id:str,user=Depends(get_verified_user)):
    model=model_info(model_id)
    entry=await asyncio.to_thread(store().get,user.id,model['provider'])
    if not entry:raise HTTPException(428,'首次使用此厂商，请配置你的 API Key。')
    if model_id not in entry['validated']:
        rate_limit(user.id)
        await validate(model,endpoint_info(model['provider'],entry['endpoint']),entry['key'])
        await asyncio.to_thread(store().mark_validated,user.id,model['provider'],model_id)
    return {'ready':True,'model_id':model_id}

@router.delete('/credentials/{provider}')
async def delete_key(provider:str,user=Depends(get_verified_user)):
    if provider not in CATALOG['providers']:raise HTTPException(404,'厂商不存在。')
    await asyncio.to_thread(store().delete,user.id,provider)
    return {'deleted':True}

async def generate_chat(request,form_data,user):
    model=model_info(form_data['model'])
    entry=await asyncio.to_thread(store().get,user.id,model['provider'])
    if not entry:raise HTTPException(428,'请先在模型选择器中配置此厂商的 API Key。')
    endpoint=endpoint_info(model['provider'],entry['endpoint'])
    messages=form_data.get('messages',[])
    first=next((m.get('content','') for m in messages if m.get('role')=='user'),'')
    metadata=form_data.get('metadata') or {}
    scope=session_scope(user.id,model['id'],metadata.get('chat_id'),first)
    internal_key=os.environ.get('WORKSTATION_AGENT_KEY') or os.environ.get('OPENAI_API_KEY','')
    envelope=runtime_envelope(internal_key,model=model['upstream_id'],endpoint=endpoint['url'],key=entry['key'],scope=scope)
    # Whitelist forwarded fields; never forward caller-supplied routing/credential data.
    payload={'model':model['id'],'messages':messages,'stream':bool(form_data.get('stream')),'_workstation_runtime':envelope}
    client=httpx.AsyncClient(timeout=httpx.Timeout(600,connect=10),trust_env=False)
    try:
        response=await client.send(client.build_request('POST','http://127.0.0.1:8642/v1/chat/completions',json=payload,
            headers={'Authorization':'Bearer '+internal_key,'X-Hermes-Session-Key':scope}),stream=True)
        if response.status_code!=200:
            await response.aclose();await client.aclose()
            raise HTTPException(502,'所选模型调用失败，请检查 API Key、余额或模型权限。')
        if not payload['stream']:
            data=json.loads(await response.aread());await response.aclose();await client.aclose()
            return JSONResponse(data)
    except httpx.HTTPError:
        await client.aclose()
        raise HTTPException(502,'科研助手连接失败，请稍后重试。') from None
    async def stream():
        try:
            async for chunk in response.aiter_bytes():yield chunk
        finally:
            await response.aclose();await client.aclose()
    return StreamingResponse(stream(),media_type='text/event-stream')
