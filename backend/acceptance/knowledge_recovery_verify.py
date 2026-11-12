import json,time
from pathlib import Path
import httpx
s=json.loads(Path('/tmp/knowledge-e2e-state.json').read_text());root='http://127.0.0.1:5173/api/v1';c=httpx.Client(trust_env=False,timeout=120);r=c.post(root+'/login',json={'username':s['users']['member']['username'],'password':s['password']});r.raise_for_status();c.headers['Authorization']='Bearer '+r.json()['access_token']
def call(method,path,**kw):
 r=c.request(method,root+path,**kw);assert r.is_success,f'{r.status_code} {r.text[:300]}';return r.json()
a=s['projects'][0];run=s['resume_run_id'];d=call('GET',f'/task-runs/{run}');knowledge=d['run']['input_snapshot']['agent_definition']['knowledge']
assert d['run']['status']=='WAITING_CONFIRMATION';assert knowledge['version_ids']==[s['versions']['newer']['id']]
print('PASS task resumes from durable confirmation boundary after container replacement',flush=True)
versions=call('GET',f'/projects/{a}/knowledge-documents/{s["recovery_document"]}/versions')['items'];assert versions[0]['status']=='READY';print('PASS durable parser queue recovery',flush=True)
response=c.post(root+f'/projects/{a}/knowledge-bases/{s["base_ids"][0]}/documents',data={'category':'api','document_id':str(s['versions']['initial']['document_id'])},files={'file':('next.txt',b'AFTER_TASK_NEW_VERSION_CANARY limit 6')});assert response.status_code==202
newer=response.json()
for _ in range(30):
 current=call('GET',f'/projects/{a}/knowledge-documents/{newer["document_id"]}/versions')['items'][0]
 if current['status']=='READY':break
 time.sleep(.2)
assert current['status']=='READY'
d=call('GET',f'/task-runs/{run}');assert d['run']['input_snapshot']['agent_definition']['knowledge']==knowledge
print('PASS existing task keeps original knowledge version after document update',flush=True)
call('POST',f'/task-runs/{run}/commands',json={'command_type':'APPROVE_PLAN','idempotency_key':s['prefix']+'_recovery_approve'})
for i in range(120):
 d=call('GET',f'/task-runs/{run}');Path('/tmp/knowledge-e2e-recovery-final.json').write_text(json.dumps(d,ensure_ascii=False,indent=2))
 if d['run']['status'] in {'SUCCEEDED','SUCCEEDED_WITH_ISSUES','FAILED','CANCELLED'}:
  print('FINAL recovered task',d['run']['status'],flush=True)
  messages=call('GET',f'/task-runs/{run}/messages');Path('/tmp/knowledge-e2e-recovery-messages.json').write_text(json.dumps(messages,ensure_ascii=False,indent=2))
  assert all(w['status']=='SUCCEEDED' for w in d['work_items']);assert d['run']['status']=='SUCCEEDED',str([m.get('metadata_json') for m in messages if m.get('message_type')=='REVIEW']);break
 time.sleep(1)
else:raise AssertionError('recovered execution timeout')
print('PASS real model task executes and produces report after restart',flush=True)
