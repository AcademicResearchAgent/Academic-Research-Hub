set -euo pipefail
/home/ubuntu/haudi-hermes/venv/bin/python -u - <<'PY'
import json,sqlite3
from pathlib import Path
dbpath=Path('/home/ubuntu/haudi-hermes/state/state.db')
db=sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)
db.row_factory=sqlite3.Row
sessions=db.execute("SELECT DISTINCT session_id FROM messages WHERE role='user' AND content LIKE ?",('%paper-audit-20260908-02%',)).fetchall()
for item in sessions:
    sid=item['session_id'];rows=db.execute('SELECT role,content,tool_name,tool_calls FROM messages WHERE session_id=? ORDER BY id',(sid,)).fetchall()
    trace=[]
    for row in rows:
        entry={'role':row['role'],'content_chars':len(row['content'] or '')}
        if row['tool_name']:entry['tool_name']=row['tool_name']
        if row['tool_calls']:
            calls=json.loads(row['tool_calls']);entry['called_tools']=[x.get('function',{}).get('name') for x in calls]
        if row['role']=='tool':
            content=row['content'] or ''
            entry['contains_scaled_dot_product']='Scaled Dot-Product' in content
            entry['contains_sqrt']='sqrt' in content
            entry['mentions_timeout']='timeout' in content.lower() or 'timed out' in content.lower()
        trace.append(entry)
    print(json.dumps({'session':sid,'trace':trace}))
db.close()
PY
