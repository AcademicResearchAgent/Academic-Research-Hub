import base64,io,json,sqlite3,time,uuid,zipfile
from pathlib import Path
import httpx
from dotenv import dotenv_values
ROOT=Path('/home/ubuntu/haudi-hermes')
account=json.loads((ROOT/'openwebui/access.json').read_text())
fixture=io.BytesIO()
with zipfile.ZipFile(fixture,'w') as z:z.writestr('main.tex','\\documentclass{article}\n\\begin{document}\nTest\n\\end{document}')
encoded=base64.b64encode(fixture.getvalue()).decode()
marker='expanded-check-'+uuid.uuid4().hex
prompt=marker+''' 这是新扩展验收，请实际调用工具，不使用终端代替：
1. 加载 npy3d-visualization Skill；使用 CFD 工具读取 /home/ubuntu/haudi-hermes/workspace/examples/cfd 的合成示例数据，绘制 frame=0、channels="0"、case="web-trial" 的曲面 PNG。
2. 使用 ars_resolvers 的 arxiv_verify 核对 Attention Is All You Need，arxiv_id=1706.03762。
3. 用 latex_template_inspect 检查下面的 ZIP，然后用 latex_project_generate 把正文改为英文 Synthetic test only，instruction="Write the confirmed synthetic test sentence, preserve the document class", material="Synthetic test only"；测试材料已经确认。调用 latex_project_validate，再调用 latex_project_confirm_package，confirmed=true（本次测试授权打包这个合成测试工程）。
template_zip_base64='''+encoded+'''
简短中文汇报实际执行结果和产物，不把合成样例当作科研证据。'''
added=False;start=time.monotonic();parts=[]
with httpx.Client(base_url='https://42.193.15.167',timeout=600,trust_env=False) as client:
    r=client.post('/api/v1/auths/signin',json={k:account[k] for k in ('email','password')});r.raise_for_status();client.headers['Authorization']='Bearer '+r.json()['token']
    try:
        if not client.get('/api/workstation/catalog').json()['credentials']['deepseek']['configured']:
            env=dotenv_values(ROOT/'state/.env');key=env.get('DEEPSEEK_API_KEY') or env.get('OPENAI_API_KEY');assert key
            r=client.post('/api/workstation/credentials',json={'model_id':'ws-deepseek-v4-pro','endpoint_id':'official','api_key':key});r.raise_for_status();added=True
        with client.stream('POST','/api/chat/completions',json={'model':'ws-deepseek-v4-pro','stream':True,'messages':[{'role':'user','content':prompt}]}) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith('data:'):continue
                raw=line[5:].strip()
                if raw=='[DONE]':break
                event=json.loads(raw);assert not event.get('error'), 'Stream error'
                a=event.get('event',{}).get('data',{}).get('activity')
                if a:print(json.dumps({k:a.get(k) for k in ('title','state','summary')},ensure_ascii=False),flush=True)
                for c in event.get('choices',[]):
                    text=c.get('delta',{}).get('content')
                    if text:parts.append(text)
        with sqlite3.connect(ROOT/'state/state.db') as db:
            row=db.execute("SELECT session_id FROM messages WHERE role='user' AND content LIKE ? ORDER BY timestamp DESC LIMIT 1",('%'+marker+'%',)).fetchone();assert row
            calls=db.execute("SELECT tool_name,content FROM messages WHERE session_id=? AND role='tool'",row).fetchall()
        results=[]
        for name,content in calls:
            if content.startswith('<untrusted_tool_result '):content=content.split('\n\n',1)[1].rsplit('\n</untrusted_tool_result>',1)[0]
            if name and (name.startswith('latex_') or name.startswith('mcp__')):
                try:value=json.loads(content)
                except ValueError:value={'text':content}
                results.append({'tool':name,'result':value})
        report={'seconds':round(time.monotonic()-start,1),'results':results,'answer':''.join(parts)}
        (ROOT/'extensions/expanded-chat-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps(report,ensure_ascii=False),flush=True)
    finally:
        if added:client.delete('/api/workstation/credentials/deepseek').raise_for_status()
        print('Temporary test credential removed.',flush=True)
