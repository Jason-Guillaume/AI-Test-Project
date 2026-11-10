import json,time
from pathlib import Path
import httpx
s=json.loads(Path('/tmp/knowledge-e2e-state.json').read_text());root='http://127.0.0.1:5173/api/v1';c=httpx.Client(trust_env=False,timeout=120);r=c.post(root+'/login',json={'username':s['users']['member']['username'],'password':s['password']});r.raise_for_status();c.headers['Authorization']='Bearer '+r.json()['access_token']
def call(method,path,**kwargs):
 r=c.request(method,root+path,**kwargs);assert r.is_success,f'{r.status_code} {r.text[:300]}';return r.json()
original=call('GET',f'/tasks/{s["task_id"]}');case=original['input_case_ids'][0]
call('POST',f'/test-cases/{case}/assertions',json={'assertion_type':'STATUS_CODE','operator':'EQ','expected_value':'200'})
task=call('POST',f'/projects/{s["projects"][0]}/tasks',json={'title':'真实任务重启恢复验收','goal':'仅执行所选健康检查用例并生成报告，以状态码200为通过标准。绑定资料仅作参考，不要求执行任何订单业务检查。','environment_id':original['environment_id'],'case_ids':original['input_case_ids'],'agent_definition_id':s['task_agent_id'],'request_key':s['prefix']+'_resume_task'})
run=task['latest_run']['id'];s['resume_run_id']=run;Path('/tmp/knowledge-e2e-state.json').write_text(json.dumps(s));print('CREATED recovery run',run,flush=True)
for i in range(90):
 d=call('GET',f'/task-runs/{run}');Path('/tmp/knowledge-e2e-resume-result.json').write_text(json.dumps(d,ensure_ascii=False,indent=2))
 if d['run']['status']=='WAITING_CONFIRMATION':
  print('READY_FOR_RESTART',run,'knowledge',d['run']['input_snapshot']['agent_definition'].get('knowledge', 'metadata not projected in old image'),flush=True);break
 if d['run']['status']=='FAILED':raise AssertionError(d['run']['error_message'])
 time.sleep(1)
else:raise AssertionError('Planner timeout')
