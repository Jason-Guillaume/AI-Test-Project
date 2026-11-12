import json, time
from pathlib import Path
import httpx
s=json.loads(Path('/tmp/knowledge-e2e-state.json').read_text());root='http://127.0.0.1:5173/api/v1';c=httpx.Client(trust_env=False,timeout=240)
r=c.post(root+'/login',json={'username':s['users']['member']['username'],'password':s['password']});assert r.status_code==200;c.headers['Authorization']='Bearer '+r.json()['access_token']
results=[]
for project in s['projects']:
    body={'project_id':project,'requirements':'基于当前 Agent 绑定的规范，生成一个订单限制测试用例。明确写出规范中的限制数字，不得使用其他项目资料；引用来源片段编号。','modules':['api'],'cases_per_module':1,'model_config_id':3}
    r=c.post(root+f'/projects/{project}/agents/{s["supervisor"]}/generate-cases',json=body)
    data=r.json();entry={'project_id':project,'http_status':r.status_code,'status':data.get('status'),'module_status':data.get('modules',[{}])[0].get('status'),'source_versions':[x['version_id'] for x in data.get('modules',[{}])[0].get('knowledge_sources',[])],'result':data}
    results.append(entry)
    Path('/tmp/knowledge-e2e-generation-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in entry.items() if k!='result'},ensure_ascii=False),flush=True)
    assert r.status_code==200 and data['status']=='COMPLETED', str(data)[:300]
    expected=s['versions']['newer']['id'] if project==s['projects'][0] else None
    if expected:assert entry['source_versions']==[expected]
print('PASS ordinary member real model generation in both projects with independent references')
