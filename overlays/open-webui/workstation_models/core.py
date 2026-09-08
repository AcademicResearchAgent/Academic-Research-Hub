"""Credential persistence and signed runtime envelopes; no web framework dependency."""
import base64
import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from cryptography.fernet import Fernet

def cipher(secret, purpose):
    if not secret:
        raise RuntimeError('Workstation secret is not configured')
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256((secret+purpose).encode()).digest()))

class CredentialStore:
    def __init__(self, path, secret):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.cipher=cipher(secret,'/workstation-credentials/v1')
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS credentials (user_id TEXT NOT NULL, provider TEXT NOT NULL, endpoint TEXT NOT NULL, secret TEXT NOT NULL, validated TEXT NOT NULL, updated_at INTEGER NOT NULL, PRIMARY KEY(user_id,provider,endpoint))')
            db.execute('CREATE TABLE IF NOT EXISTS active (user_id TEXT NOT NULL, provider TEXT NOT NULL, endpoint TEXT NOT NULL, PRIMARY KEY(user_id,provider))')
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10)
        try:
            with db:yield db
        finally:db.close()

    def put(self,user_id,provider,endpoint,key,model_id):
        # User/provider/endpoint are authenticated inside the ciphertext too.
        payload=json.dumps({'user_id':user_id,'provider':provider,'endpoint':endpoint,'key':key})
        encrypted=self.cipher.encrypt(payload.encode()).decode()
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO credentials VALUES (?,?,?,?,?,?)',
                       (user_id,provider,endpoint,encrypted,json.dumps([model_id]),int(time.time())))
            db.execute('INSERT OR REPLACE INTO active VALUES (?,?,?)',(user_id,provider,endpoint))

    def get(self,user_id,provider):
        with self.connect() as db:
            row=db.execute('SELECT c.endpoint,c.secret,c.validated FROM credentials c JOIN active a ON c.user_id=a.user_id AND c.provider=a.provider AND c.endpoint=a.endpoint WHERE c.user_id=? AND c.provider=?',(user_id,provider)).fetchone()
        if not row:return None
        payload=json.loads(self.cipher.decrypt(row[1].encode()))
        if (payload['user_id'],payload['provider'],payload['endpoint'])!=(user_id,provider,row[0]):
            raise ValueError('Credential ownership mismatch')
        return {'endpoint':row[0],'key':payload['key'],'validated':json.loads(row[2])}

    def mark_validated(self,user_id,provider,model_id):
        entry=self.get(user_id,provider)
        if entry:
            with self.connect() as db:
                db.execute('UPDATE credentials SET validated=? WHERE user_id=? AND provider=? AND endpoint=?',
                           (json.dumps(sorted(set(entry['validated']+[model_id]))),user_id,provider,entry['endpoint']))

    def delete(self,user_id,provider):
        with self.connect() as db:
            db.execute('DELETE FROM credentials WHERE user_id=? AND provider=?',(user_id,provider))
            db.execute('DELETE FROM active WHERE user_id=? AND provider=?',(user_id,provider))

def runtime_envelope(secret, *, model, endpoint, key, scope):
    payload={'model':model,'base_url':endpoint,'api_key':key,'scope':scope}
    return cipher(secret,'/workstation-runtime/v1').encrypt(json.dumps(payload).encode()).decode()

def session_scope(user_id,model_id,chat_id,first_message):
    payload=json.dumps([user_id,model_id,chat_id or '',first_message if not chat_id else ''],ensure_ascii=False,sort_keys=True)
    return 'ws-'+hashlib.sha256(payload.encode()).hexdigest()[:48]
