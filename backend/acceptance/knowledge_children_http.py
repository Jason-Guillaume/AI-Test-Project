import json
from pathlib import Path
import httpx
s=json.loads(Path('/tmp/knowledge-e2e-state.json').read_text());root='http://127.0.0.1:5173/api/v1';c=httpx.Client(trust_env=False,timeout=240);r=c.post(root+'/login',json={'username':s['users']['member']['username'],'password':s['password']});r.raise_for_status();c.headers['Authorization']='Bearer '+r.json()['access_token'];a=s['projects'][0]
r=c.post(root+f'/projects/{a}/agents/{s["supervisor"]}/generate-cases',json={'project_id':a,'requirements':'分别根据各自绑定资料生成一个测试用例，引用资料边界，不得使用其他模块或项目资料。','modules':['api','web','security','asr','ai'],'cases_per_module':1,'model_config_id':3});r.raise_for_status();data=r.json();Path('/tmp/knowledge-e2e-children-result.json').write_text(json.dumps(data,ensure_ascii=False,indent=2));assert data['status']=='COMPLETED',data['status'];assert len(data['modules'])==5
api=next(m for m in data['modules'] if m['module']=='api');security=next(m for m in data['modules'] if m['module']=='security')
assert {source['document_id'] for source in api['knowledge_sources']}=={s['versions']['initial']['document_id']}
assert {source['document_id'] for source in security['knowledge_sources']}=={s['versions']['security']['document_id']}
assert not set(source['chunk_id'] for source in api['knowledge_sources']) & set(source['chunk_id'] for source in security['knowledge_sources'])
assert all(not module['knowledge_sources'] for module in data['modules'] if module['module'] in {'web','asr','ai'})
print('PASS real five-child supervisor generation and review; API/security sources isolated; unbound children get no knowledge')
