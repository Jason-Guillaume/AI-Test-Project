import hashlib, json, os, re, time
from pathlib import Path
cases={}; warning_rows=[]; started=time.monotonic(); collected=[]; collection_errors=[]; starting_sources={}
def clean(value):
 text=str(value)
 secret=os.environ.get('TEST_POSTGRES_PASSWORD','')
 if secret: text=text.replace(secret,'<redacted>')
 return re.sub(r'postgres(?:ql)?(?:\+psycopg)?://[^\s\"\']+','<redacted-dsn>',text)
def pytest_sessionstart(session):
 starting_sources.update({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for area in ["app","tests"] for p in sorted(Path(area).rglob("*.py"))})
def pytest_collectreport(report):
 if report.failed: collection_errors.append({"nodeid":report.nodeid,"detail":clean(report.longrepr)})
def pytest_collection_finish(session):
 collected.extend(x.nodeid for x in session.items)
def pytest_runtest_logreport(report):
 row=cases.setdefault(report.nodeid,{'nodeid':report.nodeid,'outcome':'passed','duration':0})
 row['duration']+=report.duration
 if report.failed: row['outcome']='failed' if report.when=='call' else 'error'; row['detail']=clean(report.longrepr)
 elif report.skipped: row['outcome']='skipped'; row['detail']=clean(report.longrepr)
def pytest_warning_recorded(warning_message,when,nodeid,location):
 warning_rows.append({'category':warning_message.category.__name__,'message':clean(warning_message.message),'nodeid':nodeid,'when':when})
def pytest_sessionfinish(session,exitstatus):
 out=Path(os.environ['COMPREHENSIVE_REPORT_DIR']);out.mkdir(parents=True,exist_ok=True)
 manifest={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path('app').rglob('*.py'))}
 summary={'exit_code':int(exitstatus),'collected':len(collected),'passed':sum(x['outcome']=='passed' for x in cases.values()),'failed':sum(x['outcome']=='failed' for x in cases.values()),'errors':sum(x['outcome']=='error' for x in cases.values())+len(collection_errors),'skipped':sum(x['outcome']=='skipped' for x in cases.values()),'duration_seconds':round(time.monotonic()-started,3),'warnings':len(warning_rows),'warning_categories':{c:sum(x['category']==c for x in warning_rows) for c in sorted({x['category'] for x in warning_rows})},'source_digest':hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest(),'execution_checkout':str(Path.cwd()),'pytest_arguments':list(session.config.invocation_params.args),'source_changed_during_run':starting_sources!={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for area in ['app','tests'] for p in sorted(Path(area).rglob('*.py'))},'command':'env -u TEST_DATABASE_NAME TEST_POSTGRES_USER=root TEST_POSTGRES_PASSWORD=<runtime secret> TEST_POSTGRES_HOST=127.0.0.1 TEST_POSTGRES_PORT=5432 .venv/bin/python -m pytest -q --tb=no -ra -p comprehensive_pytest_plugin','database_policy':'Only testplatform_test-p<PID>, never testplatform_dev'}
 for name,data in [('summary',summary),('cases',list(cases.values())),('nodeids',collected),('warnings',warning_rows),('source-manifest',manifest),('collection-errors',collection_errors)]:
  (out/f'{name}.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
