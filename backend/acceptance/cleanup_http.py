"""Retire only this run's synthetic model resources; preserve evidence and original models."""
import json
from pathlib import Path
import httpx
s=json.loads(Path('/tmp/knowledge-e2e-state.json').read_text());root='http://127.0.0.1:5173/api/v1';c=httpx.Client(trust_env=False,timeout=60);r=c.post(root+'/login',json={'username':s['users']['admin']['username'],'password':s['password']});r.raise_for_status();c.headers['Authorization']='Bearer '+r.json()['access_token']
r=c.get(root+'/model-center/resources');r.raise_for_status();retired=[]
for resource in r.json()['items']:
 if resource['display_name'].startswith(s['prefix']):
  r=c.put(root+f'/model-center/resources/{resource["id"]}/enabled?enabled=false');r.raise_for_status();retired.append(resource['id'])
r=c.get(root+'/model-center/resources');r.raise_for_status()
assert all(x['status']=='DISABLED' for x in r.json()['items'] if x['display_name'].startswith(s['prefix']))
print('PASS retired synthetic model resources:',retired)
