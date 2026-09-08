set -euo pipefail
timeout 70 /home/ubuntu/haudi-hermes/venv/bin/python -u - <<'PY'
import json,sqlite3,xml.etree.ElementTree as ET
from pathlib import Path
import httpx
db=sqlite3.connect(Path('/home/ubuntu/haudi-hermes/state/state.db').as_uri()+'?mode=ro',uri=True)
db.row_factory=sqlite3.Row
ids=db.execute("SELECT DISTINCT session_id FROM messages WHERE role='user' AND content LIKE ?",('%paper-audit-20260908-03%',)).fetchall()
for item in ids:
    print('Session:',item['session_id'])
    rows=db.execute("SELECT content,tool_name FROM messages WHERE session_id=? AND role='tool' ORDER BY id",(item['session_id'],)).fetchall()
    for row in rows:
        value=row['content'] or ''
        print(json.dumps({'tool':row['tool_name'],'chars':len(value),'mentions_abstract':'Abstract' in value,'mentions_full_text_links':'Full text links' in value,'mentions_references':'References' in value,'mentions_truncated':'truncat' in value.lower()}))
        if row['tool_name']=='web_extract':
            print('Public test extraction start:',value[:550])
            print('Public test extraction end:',value[-250:])
            try:
                js=json.loads(value)
                print('Extract structure:',json.dumps(list(js) if isinstance(js,dict) else type(js).__name__))
                items=js if isinstance(js,list) else js.get('results',js.get('data',[]))
                if isinstance(items,list):
                    for x in items:
                        if isinstance(x,dict):
                            content=x.get('content',x.get('markdown',x.get('text','')))
                            print(json.dumps({'url':x.get('url'),'keys':list(x),'text_start':str(content)[:300]}))
            except ValueError:pass
db.close()
with httpx.Client(timeout=20) as c:
    r=c.get('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi',params={'db':'pubmed','id':'40480225,39454989','retmode':'xml'})
    print('Independent PubMed verification HTTP:',r.status_code)
    if r.status_code==200:
        xml=ET.fromstring(r.content)
        for article in xml.findall('.//PubmedArticle'):
            title=article.find('.//ArticleTitle')
            print(json.dumps({'pmid':article.findtext('.//PMID'),'title':''.join(title.itertext()),
                'doi':next((x.text for x in article.findall('.//ArticleId') if x.get('IdType')=='doi'),None),
                'publication_types':[x.text for x in article.findall('.//PublicationType')],
                'journal_year':article.findtext('.//JournalIssue/PubDate/Year')}))
PY
