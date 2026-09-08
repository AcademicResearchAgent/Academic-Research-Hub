set -euo pipefail
timeout 50 /home/ubuntu/haudi-hermes/venv/bin/python -u - <<'PY'
import json,time
import httpx
with httpx.Client(timeout=20) as c:
    for params in (
      {'search':'"base editing"','filter':'from_publication_date:2023-01-01,to_publication_date:2026-09-08','per-page':3,'select':'id,doi,title'},
      {'search.semantic':'precise correction of pathogenic single nucleotide variants with CRISPR base editors','per-page':3,'select':'id,doi,title,relevance_score'},
    ):
        started=time.monotonic()
        try:
            r=c.get('https://api.openalex.org/works',params=params)
            result={'params':params,'http':r.status_code,'seconds':round(time.monotonic()-started,1)}
            if r.status_code==200:
                js=r.json();result.update(count=js.get('meta',{}).get('count'),papers=js.get('results',[]))
            print(json.dumps(result,ensure_ascii=False),flush=True)
        except Exception as exc:print(json.dumps({'params':params,'error_type':type(exc).__name__}),flush=True)
PY
