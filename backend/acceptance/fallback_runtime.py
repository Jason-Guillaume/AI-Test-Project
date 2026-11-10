"""Exercise the real task provider factory with a disabled primary and explicit fallback."""
import json
from pathlib import Path
from types import SimpleNamespace
from app.main import app
from app.core.database.session import SessionLocal
from app.core.models.identity import User
from app.core.models.configuration import ModelConfiguration
from app.platform.model_configuration.models import ModelResource
from app.orchestration.tasks.models import TaskRun, Task
from app.orchestration.tasks.runtime.worker import TaskWorker
s=json.loads(Path('/tmp/knowledge-e2e-state.json').read_text())
with SessionLocal() as db:
    resource=db.get(ModelResource,s['test_model']);primary=db.get(ModelConfiguration,resource.legacy_model_id)
    assert not primary.is_enabled
    run=db.get(TaskRun,s['final_run_id']);task=db.get(Task,run.task_id);actor=db.get(User,s['users']['member']['id'])
    attempt=SimpleNamespace(checkpoint_json={})
    agent=SimpleNamespace(model_config_id=primary.id,config_snapshot={'fallback_model_config_ids':[3]})
    provider=TaskWorker._provider_for_agent(None,db,task,run,None,attempt,agent,actor)
    result=provider.chat('只输出验收通过四个字。','合成验收，无业务资料。')
    assert provider.last_model_config_id==3
    print('PASS configured fallback uses enabled model while primary is disabled')
    # A route without an explicit fallback must not silently select another model.
    agent.config_snapshot={}
    try:TaskWorker._provider_for_agent(None,db,task,run,None,attempt,agent,actor)
    except Exception:print('PASS disabled explicit model without fallback fails closed')
    else:raise AssertionError('disabled model unexpectedly resolved')
