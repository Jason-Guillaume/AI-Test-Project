import json,time
from pathlib import Path
import httpx
s=json.loads(Path('/tmp/knowledge-e2e-state.json').read_text());root='http://127.0.0.1:5173/api/v1';clients={}
for role in ['admin','member']:
 c=httpx.Client(trust_env=False,timeout=180);r=c.post(root+'/login',json={'username':s['users'][role]['username'],'password':s['password']});r.raise_for_status();c.headers['Authorization']='Bearer '+r.json()['access_token'];clients[role]=c

def call(role,method,path,**kwargs):
 r=clients[role].request(method,root+path,**kwargs);assert r.is_success,f'{path}: {r.status_code} {r.text[:250]}';return r.json()
a=s['projects'][0]
env=call('admin','POST',f'/projects/{a}/environments',json={'name':'e2e_local_health','display_name':'验收本地健康检查','base_url':'http://127.0.0.1:8001','is_active':True})
call('admin','POST',f'/projects/{a}/targets',json={'scheme':'http','host':'127.0.0.1','port':8001})
iface=call('member','POST',f'/projects/{a}/apis',json={'name':'验收健康检查','method':'GET','path':'/healthz','status':'ACTIVE'})
case=call('member','POST',f'/projects/{a}/test-cases',json={'name':'验收健康检查返回成功','target_type':'API','api_id':iface['id'],'enabled':True,'status':'ACTIVE'})
original=next(x for x in call('admin','GET','/agent-governance/agents') if x['workflow_template']=='api_test')
body={k:original[k] for k in ['description','workflow_template','instruction','skill_keys','tool_keys','child_agent_ids','is_enabled','test_types','purpose']}
body.update(name=s['prefix']+'_真实任务Agent',model_config_id=3,settings_json={'model_binding':'agent'})
agent=call('admin','POST','/agent-governance/agents',json=body)
call('member','PUT',f'/projects/{a}/agents/{agent["id"]}/knowledge-binding',json={'revision':0,'enabled':True,'required':True,'scopes':[{'base_id':s['base_ids'][0],'mode':'DOCUMENTS','document_ids':[s['versions']['initial']['document_id']]}]})
task=call('member','POST',f'/projects/{a}/tasks',json={'title':'真实模型知识库验收任务','goal':'只执行已选健康检查用例并生成报告，按绑定知识记录订单限制数字和来源，不新增用例，不操作其他项目。','environment_id':env.get('environment_id',env.get('id')),'case_ids':[case['id']],'agent_definition_id':agent['id'],'request_key':s['prefix']+'_real_task'})
run=task['latest_run']['id'];s.update(task_id=task['id'],task_run_id=run,task_agent_id=agent['id']);Path('/tmp/knowledge-e2e-state.json').write_text(json.dumps(s))
print('CREATED real model task',task['id'],run,flush=True)
for i in range(180):
 detail=call('member','GET',f'/task-runs/{run}');status=detail['run']['status']
 Path('/tmp/knowledge-e2e-task-result.json').write_text(json.dumps(detail,ensure_ascii=False,indent=2))
 if i%5==0: print('task status',status,detail['run']['stage'],flush=True)
 if status=='WAITING_CONFIRMATION':
  call('member','POST',f'/task-runs/{run}/commands',json={'command_type':'APPROVE_PLAN','idempotency_key':s['prefix']+'_approve'})
 elif status in {'SUCCEEDED','SUCCEEDED_WITH_ISSUES','FAILED','CANCELLED','PARTIAL_FAILED'}:
  print('FINAL',status,flush=True);assert status=='SUCCEEDED',detail['run'].get('error_message');break
 time.sleep(2)
else:raise AssertionError('task runtime timed out')
