import json
from pathlib import Path
import httpx
s=json.loads(Path('/tmp/knowledge-e2e-state.json').read_text());root='http://127.0.0.1:5173/api/v1';clients={}
for role in ['admin','member']:
 c=httpx.Client(trust_env=False,timeout=60);r=c.post(root+'/login',json={'username':s['users'][role]['username'],'password':s['password']});r.raise_for_status();c.headers['Authorization']='Bearer '+r.json()['access_token'];clients[role]=c
a=s['projects'][0];member=s['users']['member']['id'];admin=clients['admin'];c=clients['member']
search=c.post(root+f'/projects/{a}/agents/{s["api_agent"]}/knowledge-search',json={'query':''});search.raise_for_status();chunk=search.json()['items'][0]['chunk_id']
paths=[f'/projects/{a}/knowledge-bases',f'/projects/{a}/agents/{s["api_agent"]}/knowledge-sources/{chunk}',f'/task-runs/{s["resume_run_id"]}']
r=admin.delete(root+f'/projects/{a}/members/{member}');r.raise_for_status()
try:
 for path in paths:
  r=c.get(root+path);assert r.status_code==404,f'{path}: {r.status_code}'
 r=c.post(root+f'/projects/{a}/agents/{s["api_agent"]}/knowledge-search',json={'query':''});assert r.status_code==404
 print('PASS revoked project membership blocks existing token, source reads, search and task recovery')
finally:
 r=admin.put(root+f'/projects/{a}/members/{member}',json={'user_id':member,'role':'editor'});r.raise_for_status()
for path in paths:assert c.get(root+path).status_code==200
print('PASS access restored only after explicit membership restoration')
