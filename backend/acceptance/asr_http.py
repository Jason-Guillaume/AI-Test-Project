import json,time
from pathlib import Path
import httpx
s=json.loads(Path('/tmp/knowledge-e2e-state.json').read_text());root='http://127.0.0.1:5173/api/v1';clients={}
for role in ['admin','member']:
 c=httpx.Client(trust_env=False,timeout=60);r=c.post(root+'/login',json={'username':s['users'][role]['username'],'password':s['password']});r.raise_for_status();c.headers['Authorization']='Bearer '+r.json()['access_token'];clients[role]=c

def call(role,method,path,**kwargs):
 r=clients[role].request(method,root+path,**kwargs);assert r.is_success,f'{path}: {r.status_code} {r.text[:300]}';return r.json()
a=s['projects'][0]
if not any(t['host']=='backend' and t['port']==8770 for t in call('admin','GET',f'/projects/{a}/targets')):
 call('admin','POST',f'/projects/{a}/targets',json={'scheme':'http','host':'backend','port':8770})
resource=call('admin','POST','/model-center/resources',json={'category':'ASR','visibility':'PLATFORM','display_name':s['prefix']+'_ASR验收边界','provider':'custom','adapter_key':'generic-json-http','model_name':'synthetic-asr','endpoint':'http://backend:8770/asr','config':{'request_template':{'audio':'{{audio.url}}','model':'{{connection.model_id}}','parameters':'{{experiment.parameters}}'},'response_mapping':{'text_pointer':'/text'}},'capabilities':['transcription']})
resources=[resource]
for index in [1,2]:
 resources.append(call('admin','POST','/model-center/resources',json={'category':'ASR','visibility':'PLATFORM','display_name':s['prefix']+'_ASR参考'+str(index),'provider':'custom','adapter_key':'generic-json-http','model_name':'synthetic-asr-'+str(index),'endpoint':'http://backend:8770/asr','config':{'request_template':{'audio':'{{audio.url}}','model':'{{connection.model_id}}','parameters':'{{experiment.parameters}}'},'response_mapping':{'text_pointer':'/text'}},'capabilities':['transcription']}))
audio=call('member','POST','/asr/audio',json={'project_id':a,'audio':{'name':'合成静音验收样本','url':'http://backend:8770/audio.wav','duration_seconds':1}})
slots=[{'slot':role,'resource_id':res['id'],'revision_id':res['current_revision']['id'],'profile_id':res['current_revision']['profiles'][0]['id']} for role,res in zip(['TEST','REFERENCE_A','REFERENCE_B'],resources)]
payload={'project_id':a,'audio_ids':[audio['id']],'model_slots':slots}
job=call('member','POST','/asr/jobs',json=payload)
s.update(asr_resource=resource['id'],asr_audio=audio['id'],asr_slots=slots,asr_job=job['id']);Path('/tmp/knowledge-e2e-state.json').write_text(json.dumps(s))
print('CREATED ASR job',job['id'],flush=True)
for _ in range(60):
 detail=call('member','GET',f'/asr/jobs/{job["id"]}');Path('/tmp/knowledge-e2e-asr-result.json').write_text(json.dumps(detail,ensure_ascii=False,indent=2))
 if detail['status'] not in {'QUEUED','RUNNING','PENDING'}:
  print('FINAL ASR',detail['status'],flush=True);print(json.dumps(detail,ensure_ascii=False)[:800],flush=True);break
 time.sleep(1)
