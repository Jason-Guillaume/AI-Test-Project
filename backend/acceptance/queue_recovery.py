import json,hashlib
import app.core.models
from pathlib import Path
from app.core.database.session import SessionLocal
from app.knowledge.models import KnowledgeDocument,KnowledgeVersion
from app.orchestration.tasks.models import TaskRun
s=json.loads(Path('/tmp/knowledge-e2e-state.json').read_text())
with SessionLocal() as db:
 run=db.get(TaskRun,s['resume_run_id']);print('PINNED_KNOWLEDGE',run.input_snapshot['agent_definition']['knowledge'])
 doc=KnowledgeDocument(project_id=s['projects'][0],base_id=s['base_ids'][0],name='重启恢复.txt');db.add(doc);db.flush()
 content=b'RESTART_RECOVERED_CANARY'
 version=KnowledgeVersion(document_id=doc.id,version=1,digest=hashlib.sha256(content).hexdigest(),filename='restart.txt',content=content,status='RECOVERY_WAIT',attempts=0);db.add(version);db.commit()
 s['recovery_document']=doc.id;s['recovery_version']=version.id
 Path('/tmp/knowledge-e2e-state.json').write_text(json.dumps(s));print('QUEUED_FOR_RESTART',version.id)
