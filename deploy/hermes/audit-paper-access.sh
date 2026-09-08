set -euo pipefail
cd /home/ubuntu/haudi-hermes/source
export HERMES_HOME=/home/ubuntu/haudi-hermes/state
timeout 180 /home/ubuntu/haudi-hermes/venv/bin/python -u - <<'PY'
import importlib.util,json,os,time,concurrent.futures,xml.etree.ElementTree as ET
from pathlib import Path
import httpx,yaml
from dotenv import load_dotenv
root=Path('/home/ubuntu/haudi-hermes')
load_dotenv(root/'state/.env')
cfg=yaml.safe_load((root/'state/config.yaml').read_text())
print('API toolsets:',json.dumps(cfg.get('platform_toolsets',{}).get('api_server')))
print('Web selectors:',json.dumps({k:cfg.get('web',{}).get(k) for k in ('backend','search_backend','extract_backend','keyless_fallback')}))
keys=['FIRECRAWL_API_KEY','TAVILY_API_KEY','EXA_API_KEY','BRAVE_SEARCH_API_KEY','SEARXNG_URL','NCBI_API_KEY','OPENALEX_API_KEY','SEMANTIC_SCHOLAR_API_KEY']
print('Credential presence only:',json.dumps({k:bool(os.environ.get(k)) for k in keys}))
print('MCP server names:',json.dumps(list((cfg.get('mcp_servers') or {}).keys())))
print('Research skills:',json.dumps({name:(root/f'state/skills/research/{name}/SKILL.md').exists() for name in ('arxiv','grounded-citations')}))
print('PDF/search packages:',json.dumps({name:importlib.util.find_spec(name) is not None for name in ('pypdf','fitz','pdfplumber','ddgs')}))
from tools.web_tools import _get_search_backend,_get_extract_backend,check_web_api_key
print('Resolved search backend:',_get_search_backend())
print('Resolved extract backend:',_get_extract_backend())
print('Web tools availability:',check_web_api_key())
probes={
 'arXiv search':('https://export.arxiv.org/api/query',{'search_query':'ti:attention','max_results':1}),
 'PubMed search':('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi',{'db':'pubmed','term':'CRISPR','retmode':'json','retmax':1}),
 'Europe PMC search':('https://www.ebi.ac.uk/europepmc/webservices/rest/search',{'query':'CRISPR','format':'json','pageSize':1}),
 'Crossref metadata':('https://api.crossref.org/works',{'query.title':'Attention is all you need','rows':1}),
 'OpenAlex search (no key)':('https://api.openalex.org/works',{'search':'CRISPR','per-page':1}),
 'Semantic Scholar search (no key)':('https://api.semanticscholar.org/graph/v1/paper/search',{'query':'CRISPR','limit':1,'fields':'title,openAccessPdf'}),
 'arXiv PDF':('https://arxiv.org/pdf/1706.03762',{}),
 'PMC full text XML':('https://www.ebi.ac.uk/europepmc/webservices/rest/PMC3257301/fullTextXML',{}),
}
def probe(item):
    name,(url,params)=item; started=time.monotonic()
    result={'probe':name}
    try:
        with httpx.Client(timeout=25,follow_redirects=True,headers={'User-Agent':'HaudiResearchWorkstation/1.0 (connectivity audit)'}) as client:
            r=client.get(url,params=params)
            result.update(http=r.status_code,bytes=len(r.content))
            if r.status_code==200:
                if name=='arXiv search':result['entries']=len(ET.fromstring(r.content).findall('{http://www.w3.org/2005/Atom}entry'))
                elif name=='PubMed search':result['ids']=r.json().get('esearchresult',{}).get('idlist')
                elif name=='Europe PMC search':result['hits']=r.json().get('hitCount')
                elif name=='Crossref metadata':result['items']=len(r.json().get('message',{}).get('items',[]))
                elif name=='OpenAlex search (no key)':result['results']=len(r.json().get('results',[]))
                elif name=='Semantic Scholar search (no key)':result['results']=len(r.json().get('data',[]))
                elif name=='arXiv PDF':
                    result['pdf_signature']=r.content.startswith(b'%PDF')
                    if result['pdf_signature'] and importlib.util.find_spec('pypdf'):
                        import io
                        from pypdf import PdfReader
                        pdf=PdfReader(io.BytesIO(r.content));result['pages']=len(pdf.pages);result['first_page_text_chars']=len(pdf.pages[0].extract_text() or '')
                elif name=='PMC full text XML':
                    xml=ET.fromstring(r.content);result['body_present']=xml.find('.//body') is not None;result['body_text_chars']=len(''.join(xml.find('.//body').itertext())) if result['body_present'] else 0
    except Exception as exc: result['error_type']=type(exc).__name__
    result['seconds']=round(time.monotonic()-started,1)
    return result
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    futures=[pool.submit(probe,item) for item in probes.items()]
    for future in concurrent.futures.as_completed(futures): print(json.dumps(future.result()),flush=True)
PY
