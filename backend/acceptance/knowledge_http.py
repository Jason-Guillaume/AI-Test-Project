"""Live HTTP acceptance: requires synthetic fixture state created in the local development DB."""
import io
import json
import os
import time
import zipfile
from pathlib import Path
import httpx
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

STATE = Path(os.environ.get('ACCEPTANCE_STATE', '/tmp/knowledge-e2e-state.json'))
state = json.loads(STATE.read_text())
root = os.environ.get('ACCEPTANCE_URL', 'http://127.0.0.1:5173/api/v1')
clients = {}
results = []


def check(name, value):
    results.append({'name': name, 'passed': bool(value)})
    print(('PASS ' if value else 'FAIL ') + name, flush=True)
    if not value:
        raise AssertionError(name)


def call(actor, method, path, expected=200, **kwargs):
    response = clients[actor].request(method, root+path, **kwargs)
    assert response.status_code == expected, f'{method} {path}: {response.status_code} {response.text[:300]}'
    return response.json() if response.content else None


def parse_wait(project, doc, wanted='READY'):
    for _ in range(60):
        rows = call('admin','GET',f'/projects/{project}/knowledge-documents/{doc}/versions')['items']
        if rows[0]['status'] in {'READY','FAILED'}:
            return rows[0]
        time.sleep(.25)
    raise AssertionError('parse timeout')


def upload(project, base, name, data, category='', document=None):
    fields={'category': category}
    if document: fields['document_id']=str(document)
    row=call('member','POST',f'/projects/{project}/knowledge-bases/{base}/documents',202,files={'file':(name,data)},data=fields)
    return parse_wait(project,row['document_id'])


def bind(project, agent, scopes, required=False, expected_revision=None):
    path=f'/projects/{project}/agents/{agent}/knowledge-binding'
    old=call('member','GET',path)
    return call('member','PUT',path,json={'revision':old['revision'] if expected_revision is None else expected_revision,'enabled':True,'required':required,'scopes':scopes})


def search(project, agent, query=''):
    return call('member','POST',f'/projects/{project}/agents/{agent}/knowledge-search',json={'query':query})


def main():
    for label,user in state['users'].items():
        client=httpx.Client(timeout=180, trust_env=False)
        response=client.post(root+'/login',json={'username':user['username'],'password':state['password']})
        assert response.status_code==200, response.status_code
        client.headers['Authorization']='Bearer '+response.json()['access_token']
        clients[label]=client
    a,b=state['projects']
    check('unauthenticated knowledge rejected', httpx.get(root+f'/projects/{a}/knowledge-bases', trust_env=False).status_code==401)
    base_a=call('member','POST',f'/projects/{a}/knowledge-bases',201 if False else 200,json={'name':'同名规范库'})['id']
    base_b=call('member','POST',f'/projects/{b}/knowledge-bases',json={'name':'同名规范库'})['id']
    va=upload(a,base_a,'规范.txt',b'MALL_API_CANARY order limit 3', 'api')
    vb=upload(b,base_b,'规范.txt',b'PAYMENT_PRIVATE_CANARY settlement limit 7','api')
    check('async TXT parsed in both projects',va['status']==vb['status']=='READY')
    md=upload(a,base_a,'安全.md',b'# Security\nSECURITY_CANARY password length 14','security')
    z=io.BytesIO()
    with zipfile.ZipFile(z,'w') as archive:
        archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>DOCX_CANARY</w:t></w:r></w:p></w:body></w:document>')
    docx=upload(a,base_a,'文档.docx',z.getvalue())
    writer=PdfWriter(); page=writer.add_blank_page(300,300)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 30 200 Td (PDF_TEXT_CANARY) Tj ET')
    page[NameObject('/Contents')]=writer._add_object(stream)
    pdf=io.BytesIO();writer.write(pdf)
    pv=upload(a,base_a,'文本.pdf',pdf.getvalue())
    check('Markdown DOCX text PDF parsed',all(v['status']=='READY' for v in [md,docx,pv]))
    agents=call('admin','GET','/agent-governance/agents')
    main_agent=next(agent for agent in agents if agent['workflow_template']=='case_generation' and agent['child_agent_ids'])
    children={key:next(agent for agent in agents if key in agent['tool_keys']) for key in ['case_generation.generate_api','case_generation.generate_security']}
    api_agent=children['case_generation.generate_api']['id'];security_agent=children['case_generation.generate_security']['id']
    def doc_scope(base,doc):return [{'base_id':base,'mode':'DOCUMENTS','document_ids':[doc],'categories':[]}]
    bind(a,api_agent,doc_scope(base_a,va['document_id']),True)
    bind(b,api_agent,[{'base_id':base_b,'mode':'ALL'}],True)
    bind(a,security_agent,[{'base_id':base_a,'mode':'CATEGORIES','categories':['security']}],True)
    sa=search(a,api_agent);sb=search(b,api_agent);ss=search(a,security_agent)
    check('same Agent reads separate project documents','MALL_API_CANARY' in str(sa) and 'PAYMENT_PRIVATE_CANARY' not in str(sa) and 'PAYMENT_PRIVATE_CANARY' in str(sb))
    check('different child Agents read distinct scopes','SECURITY_CANARY' in str(ss) and 'MALL_API_CANARY' not in str(ss) and 'SECURITY_CANARY' not in str(sa))
    check('unbound supervisor receives no sources',search(a,main_agent['id'])['items']==[])
    call('outsider','GET',f'/projects/{a}/knowledge-bases',404)
    call('member','GET',f'/projects/{a}/knowledge-bases/{base_b}/documents',404)
    call('member','PUT',f'/projects/{a}/agents/{api_agent}/knowledge-binding',404,json={'revision':1,'enabled':True,'required':False,'scopes':[{'base_id':base_b,'mode':'ALL'}]})
    check('cross project enumeration and binding rejected',True)
    path=f'/projects/{a}/agents/{api_agent}/knowledge-sources/{sa["items"][0]["chunk_id"]}'
    call('member','GET',path)
    call('member','GET',f'/projects/{a}/agents/{security_agent}/knowledge-sources/{sa["items"][0]["chunk_id"]}',404)
    check('source preview obeys Agent scope',True)
    old=call('member','GET',f'/projects/{a}/agents/{api_agent}/knowledge-binding')
    call('member','PUT',f'/projects/{a}/agents/{api_agent}/knowledge-binding',400,json={**old,'revision':0})
    check('stale binding revision rejected',True)
    failed=upload(a,base_a,'规范.txt',b'\xff',document=va['document_id'])
    check('failed update preserves effective old version',failed['status']=='FAILED' and search(a,api_agent)['snapshot']['version_ids']==[va['id']])
    call('member','POST',f'/projects/{a}/knowledge-document-versions/{failed["id"]}/commands',json={'action':'retry'})
    retried=parse_wait(a,va['document_id'])
    check('failed parse retries with incremented attempt',retried['attempts']>=2 and retried['status']=='FAILED')
    newer=upload(a,base_a,'规范.txt',b'MALL_NEW_VERSION_CANARY order limit 5',document=va['document_id'])
    check('successful update switches new runs',search(a,api_agent)['snapshot']['version_ids']==[newer['id']])
    call('member','GET',path)
    check('historical source remains previewable in authorized document',True)
    call('member','POST',f'/projects/{a}/knowledge-document-versions/{newer["id"]}/commands',json={'action':'disable'})
    call('member','POST',f'/projects/{a}/agents/{api_agent}/knowledge-search',400,json={'query':''})
    call('member','GET',path,400)
    check('disabled source blocks required knowledge and old preview',True)
    call('member','POST',f'/projects/{a}/knowledge-document-versions/{newer["id"]}/commands',json={'action':'enable'})
    resources=call('member','GET',f'/model-center/available?project_id={a}')['items']
    check('ordinary member has global enabled models without grants',bool(resources))
    model=call('admin','POST','/model-center/resources',201,json={'category':'TEXT_GENERATION','visibility':'PLATFORM','display_name':state['prefix']+'_disabled_model','provider':'custom','adapter_key':'openai-compatible-chat','model_name':'acceptance-local','endpoint':'http://127.0.0.1:9/v1','enabled':True})
    check('new global model visible without grant',model['id'] in [r['id'] for r in call('member','GET',f'/model-center/available?project_id={a}')['items']])
    call('member','PUT',f'/model-center/resources/{model["id"]}/enabled?enabled=false',403)
    call('admin','PUT',f'/model-center/resources/{model["id"]}/enabled?enabled=false')
    check('disabled model disappears across projects',all(model['id'] not in [r['id'] for r in call('member','GET',f'/model-center/available?project_id={p}')['items']] for p in [a,b]))
    state.update({'base_ids':[base_a,base_b],'versions':{'initial':va,'newer':newer,'security':md},'api_agent':api_agent,'security_agent':security_agent,'supervisor':main_agent['id'],'test_model':model['id']})
    STATE.write_text(json.dumps(state));STATE.chmod(0o600)

if __name__=='__main__':
    try:main()
    finally:
        target=Path(os.environ.get('ACCEPTANCE_REPORT','/tmp/knowledge-e2e-http-results.json'))
        target.write_text(json.dumps(results,ensure_ascii=False,indent=2))
