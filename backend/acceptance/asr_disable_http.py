import json,sys,time
from pathlib import Path
import httpx
s=json.loads(Path('/tmp/knowledge-e2e-state.json').read_text());root='http://127.0.0.1:5173/api/v1';clients={}
for role in ['admin','member']:
 c=httpx.Client(trust_env=False,timeout=60);r=c.post(root+'/login',json={'username':s['users'][role]['username'],'password':s['password']});r.raise_for_status();c.headers['Authorization']='Bearer '+r.json()['access_token'];clients[role]=c
def call(role,method,path,**kw):
 r=clients[role].request(method,root+path,**kw);assert r.is_success,f'{r.status_code} {r.text[:300]}';return r.json()
if sys.argv[1]=='queue':
 payload={'project_id':s['projects'][0],'audio_ids':[s['asr_audio']],'model_slots':s['asr_slots']}
 job=call('member','POST','/asr/jobs',json=payload);s['asr_disabled_job']=job['id'];Path('/tmp/knowledge-e2e-state.json').write_text(json.dumps(s))
 call('admin','PUT',f'/model-center/resources/{s["asr_resource"]}/enabled?enabled=false')
 r=clients['member'].post(root+'/asr/jobs',json=payload);assert r.status_code==404,r.text
 print('PASS disabled ASR resource rejected on new submission; queued snapshot retained',job['id'])
else:
 for _ in range(60):
  job=call('member','GET',f'/asr/jobs/{s["asr_disabled_job"]}')
  if all(r['status'] in {'SUCCEEDED','FAILED','CANCELLED'} for r in job['runs']):break
  time.sleep(1)
 Path('/tmp/knowledge-e2e-asr-disabled-result.json').write_text(json.dumps(job,ensure_ascii=False,indent=2))
 primary=next(r for r in job['runs'] if r['role']=='TEST');refs=[r for r in job['runs'] if r['role']!='TEST']
 assert primary['status']=='FAILED' and all(r['status']=='SUCCEEDED' for r in refs),str([(r['role'],r['status'],r['error_message']) for r in job['runs']])
 assert call('member','GET',f'/asr/jobs/{s["asr_job"]}')['status']=='COMPLETED'
 print('PASS ASR queued old snapshot blocked by disabled model; reference models completed; history preserved')
