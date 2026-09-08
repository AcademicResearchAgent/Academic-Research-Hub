set -euo pipefail
timeout 180 /home/ubuntu/haudi-hermes/venv/bin/python -u - <<'PY'
import concurrent.futures,json,time,xml.etree.ElementTree as ET
from datetime import datetime,timezone
import httpx
records=[]
def emit(record):
    record['checked_at']=datetime.now(timezone.utc).isoformat()
    records.append(record)
    print(json.dumps(record,ensure_ascii=False),flush=True)
def request(name,url,params=None,parser=None):
    start=time.monotonic();out={'test':name,'url':url,'params':params or {}}
    result=None
    try:
        with httpx.Client(timeout=18,follow_redirects=True,headers={'User-Agent':'HaudiResearchWorkstation/1.0 (public scholarly API feasibility probe)'}) as client:
            r=client.get(url,params=params)
            out.update(http=r.status_code,bytes=len(r.content))
            if r.status_code==200:
                result=parser(r) if parser else r.json()
                out['result']=result
    except Exception as exc:out['error_type']=type(exc).__name__
    out['seconds']=round(time.monotonic()-start,2);emit(out)
    return result
def epmc_summary(r):
    js=r.json();items=js.get('resultList',{}).get('result',[])
    return {'count':js.get('hitCount'),'papers':[{
        'id':i.get('id'),'pmcid':i.get('pmcid'),'doi':i.get('doi'),'title':i.get('title'),
        'year':i.get('pubYear'),'abstract_chars':len(i.get('abstractText','')),
        'is_open_access':i.get('isOpenAccess'),'has_fulltext':i.get('inEPMC')
    } for i in items]}
def oa_summary(r):
    js=r.json();items=js.get('results',[js])
    return {'count':js.get('meta',{}).get('count'),'papers':[{
        'id':i.get('id'),'doi':i.get('doi'),'title':i.get('title'),'year':i.get('publication_year'),
        'abstract_available':bool(i.get('abstract_inverted_index')),
        'referenced_works_count':len(i.get('referenced_works',[])),
        'cited_by_count':i.get('cited_by_count'),'open_access':i.get('open_access'),
        'has_content':i.get('has_content'),'content_urls':i.get('content_urls'),
        'oa_location_count':sum(bool(x.get('is_oa')) for x in i.get('locations',[])),
        'reference_ids_sample':i.get('referenced_works',[])[:2]
    } for i in items]}
def pubmed_xml(r):
    xml=ET.fromstring(r.content);items=xml.findall('.//PubmedArticle')
    return {'papers':[{'pmid':i.findtext('.//PMID'),'title':''.join(i.find('.//ArticleTitle').itertext()) if i.find('.//ArticleTitle') is not None else '',
        'abstract_chars':sum(len(''.join(x.itertext())) for x in i.findall('.//AbstractText')),
        'mesh_terms':len(i.findall('.//MeshHeading')),
        'doi':next((x.text for x in i.findall('.//ArticleId') if x.get('IdType')=='doi'),None)} for i in items]}
seed=request('Europe PMC precise lookup and abstract','https://www.ebi.ac.uk/europepmc/webservices/rest/search',
    {'query':'PMCID:PMC3257301','format':'json','resultType':'core','pageSize':1},epmc_summary)
paper=(seed or {}).get('papers',[{}])[0]
pmid=paper.get('id');doi=paper.get('doi')
jobs=[
 ('Europe PMC topic search with abstracts','https://www.ebi.ac.uk/europepmc/webservices/rest/search',{'query':'TITLE_ABS:"base editing" AND FIRST_PDATE:[2023-01-01 TO 2026-09-08]','format':'json','resultType':'core','pageSize':3},epmc_summary),
 ('OpenAlex topic search','https://api.openalex.org/works',{'search':'base editing','filter':'from_publication_date:2023-01-01,to_publication_date:2026-09-08','per-page':3},oa_summary),
 ('PubMed structured title/abstract date query','https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi',{'db':'pubmed','term':'"base editing"[Title/Abstract] AND 2023:2026[Date - Publication]','retmode':'json','retmax':3},lambda r:{'count':r.json().get('esearchresult',{}).get('count'),'ids':r.json().get('esearchresult',{}).get('idlist'),'translated_query':r.json().get('esearchresult',{}).get('querytranslation')}),
 ('bioRxiv daily discovery','https://api.biorxiv.org/details/biorxiv/2026-09-01/2026-09-01/0',{},lambda r:{'status':r.json().get('messages'),'returned':len(r.json().get('collection',[])),'sample':[{'doi':i.get('doi'),'title':i.get('title'),'version':i.get('version'),'published':i.get('published'),'abstract_chars':len(i.get('abstract',''))} for i in r.json().get('collection',[])[:2]]}),
 ('medRxiv daily discovery','https://api.biorxiv.org/details/medrxiv/2026-09-01/2026-09-01/0',{},lambda r:{'status':r.json().get('messages'),'returned':len(r.json().get('collection',[])),'sample':[{'doi':i.get('doi'),'title':i.get('title'),'version':i.get('version')} for i in r.json().get('collection',[])[:2]]}),
 ('arXiv exact ID API','https://export.arxiv.org/api/query',{'id_list':'1706.03762'},lambda r:{'entries':len(ET.fromstring(r.content).findall('{http://www.w3.org/2005/Atom}entry'))}),
]
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    futures=[pool.submit(request,*job) for job in jobs]
    for f in concurrent.futures.as_completed(futures):f.result()
if pmid:
    request('PubMed fetched abstract and identifiers','https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi',{'db':'pubmed','id':pmid,'retmode':'xml'},pubmed_xml)
    for kind in ('references','citations'):
        request('Europe PMC '+kind,f'https://www.ebi.ac.uk/europepmc/webservices/rest/MED/{pmid}/{kind}',{'format':'json','pageSize':3},
          lambda r:{'hitCount':r.json().get('hitCount'),'lists':{k:len(next(iter(v.values()),[])) if isinstance(v,dict) else 0 for k,v in r.json().items() if k.endswith('List')}})
if doi:
    request('Crossref DOI verification','https://api.crossref.org/works/'+doi,{},lambda r:{k:r.json()['message'].get(k) for k in ('DOI','title','type','reference-count','is-referenced-by-count')})
    oa=request('OpenAlex DOI and OA resolution','https://api.openalex.org/works/https://doi.org/'+doi,{},oa_summary)
    opaper=(oa or {}).get('papers',[{}])[0]
    if opaper.get('id'):
        request('OpenAlex citing papers','https://api.openalex.org/works',{'filter':'cites:'+opaper['id'],'per-page':3},oa_summary)
    request('Semantic Scholar exact DOI lookup without key','https://api.semanticscholar.org/graph/v1/paper/DOI:'+doi,
       {'fields':'title,year,externalIds,openAccessPdf,referenceCount,citationCount'},lambda r:r.json())
    request('Crossref BibTeX export','https://api.crossref.org/works/'+doi+'/transform/application/x-bibtex',{},
       lambda r:{'bibtex_record':r.text.lstrip().startswith('@'),'chars':len(r.text),'contains_doi':doi.lower() in r.text.lower()})
full=request('Europe PMC structured fulltext and references','https://www.ebi.ac.uk/europepmc/webservices/rest/PMC3257301/fullTextXML',{},
    lambda r:{'sections':len(ET.fromstring(r.content).findall('.//body//sec')),
      'section_titles':[''.join(x.itertext()) for x in ET.fromstring(r.content).findall('.//body//sec/title')][:6],
      'references':len(ET.fromstring(r.content).findall('.//ref-list/ref')),
      'body_chars':len(''.join(ET.fromstring(r.content).find('.//body').itertext()))})
emit({'summary':{'requests':len(records),'http_200':sum(r.get('http')==200 for r in records),'non_200_or_error':[r['test'] for r in records if r.get('http')!=200]},'scope':'Small public API feasibility probes; not recall/precision or model quality benchmark.'})
PY
