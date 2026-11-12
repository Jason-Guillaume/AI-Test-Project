"""合成数据验证评测口径、治理授权与种子幂等性，无网络调用。"""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agents.models import AgentDefinition, AgentDefinitionRevision
from app.skills.models import SkillDefinition, SkillDefinitionRevision
from app.core.database.base import Base
from app.tools.models import ToolDefinitionOverride
from app.tools.registry import get_binding
from app.tools.builtin.ai_evaluation.evaluation_tools import (
    score_transcript, check_output, get_job_summary, get_comparison_summary,
)
from app.platform.agent_governance.services.evaluation_service import invoke_evaluation


def test_reference_denominator_and_insertions():
    assert score_transcript('你好', '你')['error_rate'] == .5
    assert score_transcript('你', '你好世界')['error_rate'] == 3
    assert score_transcript('one two', 'one', unit='word')['error_rate'] == .5
    assert score_transcript('', '插入')['error_rate'] is None
    assert score_transcript('', '')['status'] == 'EMPTY_REFERENCE'
    assert score_transcript('a'*1500, 'b'*1500)['status'] == 'LIMIT_EXCEEDED'


def test_normalization_and_rule_failures():
    assert score_transcript('你好，A', '你好a', ignore_case=True, ignore_punctuation=True)['error_rate'] == 0
    assert score_transcript('é', 'e\u0301')['error_rate'] == 0
    assert check_output('x')['status'] == 'NO_RULES'
    assert check_output('[]', require_json_object=True)['passed'] == 0
    result = check_output('{"answer":"北京"}', required_phrases=['北京'], forbidden_phrases=['秘密'], require_json_object=True)
    assert result['passed'] == result['total'] == 3
    assert check_output('hello', expected='world')['pass_rate'] == 0


def _db():
    db = Mock()
    agent = SimpleNamespace(id=1, version=2, is_enabled=True, tool_keys=['asr.score_transcript'])
    db.get.side_effect = lambda model, key: agent if model is AgentDefinition else None
    return db, agent


def test_invocation_requires_enabled_grant_and_schema():
    db, agent = _db()
    with patch('app.platform.agent_governance.services.evaluation_service.get_project_or_404'):
        result = invoke_evaluation(db, SimpleNamespace(id=1), 1, 10, 'asr.score_transcript', {'reference':'你好', 'hypothesis':'你好'})
        assert result['result']['error_rate'] == 0
        assert result['agent_version'] == 2
        for arguments in ({'reference':'a','hypothesis':'b','actor':1}, {'reference':'a','hypothesis':'b','unit':'bogus'}, {'reference':'a'*4001,'hypothesis':''}):
            with pytest.raises(HTTPException):
                invoke_evaluation(db, None, 1, 10, 'asr.score_transcript', arguments)
        agent.is_enabled = False
        with pytest.raises(HTTPException):
            invoke_evaluation(db, None, 1, 10, 'asr.score_transcript', {})
        agent.is_enabled = True
        with pytest.raises(HTTPException):
            invoke_evaluation(db, None, 1, 10, 'ai.check_output', {})
        db.get.side_effect = lambda model, key: agent if model is AgentDefinition else SimpleNamespace(is_enabled=False)
        with pytest.raises(HTTPException):
            invoke_evaluation(db, None, 1, 10, 'asr.score_transcript', {})


@pytest.mark.parametrize('handler,service_name', [(get_job_summary,'job_service'), (get_comparison_summary,'comparison_service')])
def test_cross_project_resource_rejected(handler, service_name):
    db = Mock()
    db.get.return_value = SimpleNamespace(project_id=99)
    with patch('app.tools.builtin.ai_evaluation.evaluation_tools.get_project_or_404'), patch(f'app.tools.builtin.ai_evaluation.evaluation_tools.{service_name}') as service:
        with pytest.raises(HTTPException) as error:
            handler(db, 10, SimpleNamespace(id=1), 123)
        assert error.value.status_code == 404
        assert not service.mock_calls


def test_seed_preserves_edits_and_has_valid_links():
    source = Path(__file__).resolve().parents[3] / 'alembic/versions/0043_testing_agent_presets.py'
    spec = spec_from_file_location('testing_agent_seed', source)
    seed = module_from_spec(spec)
    spec.loader.exec_module(seed)
    engine = create_engine('sqlite://')
    tables = [m.__table__ for m in (SkillDefinition, SkillDefinitionRevision, AgentDefinition, AgentDefinitionRevision)]
    Base.metadata.create_all(engine, tables=tables)
    with engine.begin() as conn, patch.object(seed.op, 'get_bind', return_value=conn):
        seed.upgrade()
        conn.execute(AgentDefinition.__table__.update().where(AgentDefinition.key == seed.AGENTS[0]['key']).values(name='用户编辑'))
        seed.upgrade()
    with Session(engine) as db:
        assert db.query(AgentDefinition).count() == 6
        assert db.query(SkillDefinition).count() == 5
        assert db.query(AgentDefinitionRevision).count() == 6
        assert db.query(SkillDefinitionRevision).count() == 5
        assert db.query(AgentDefinition).filter_by(key=seed.AGENTS[0]['key']).one().name == '用户编辑'
    for agent in seed.AGENTS:
        for tool in agent['tool_keys']:
            # report.review 是现有任务审阅节点，独立于内置工具 dispatcher。
            if tool != 'report.review':
                assert get_binding(tool, channel='fixed')


def test_http_invocation_contract():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.platform.agent_governance.router import router
    from app.core.security.auth import require_platform_admin
    from app.core.database.session import get_db
    app = FastAPI()
    app.include_router(router)
    db, _ = _db()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_platform_admin] = lambda: SimpleNamespace(id=1)
    with TestClient(app) as client, patch('app.platform.agent_governance.services.evaluation_service.get_project_or_404'):
        path = '/agent-governance/agents/1/evaluation-tools/asr.score_transcript/invoke'
        response = client.post(path, json={'project_id':10, 'arguments':{'reference':'你好', 'hypothesis':'你好'}})
        assert response.status_code == 200
        assert response.json()['result']['error_rate'] == 0
        assert client.post(path, json={'project_id':-1}).status_code == 422
        assert client.post(path, json={'project_id':10, 'arguments':{'actor':1}}).status_code == 400
