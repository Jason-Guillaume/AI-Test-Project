"""使用合成模型输出验证 LangGraph 编排与模块授权，无真实模型调用。"""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agents.models import AgentDefinition, AgentDefinitionRevision
from app.knowledge.models import KnowledgeBase, KnowledgeDocument, KnowledgeVersion, KnowledgeChunk, KnowledgeBinding
from app.skills.models import SkillDefinition, SkillDefinitionRevision
from app.tools.models import ToolDefinitionOverride
from app.core.database.base import Base
from app.agents.services.case_generation_service import generate_case_suite
from app.agents.services.link_validation import validate_agent_links
from app.tools.builtin.case_generation.contracts import GenerationRequest


@pytest.fixture
def sandbox():
    spec = spec_from_file_location('generation_seed', Path(__file__).resolve().parents[3] / 'alembic/versions/0044_case_generation_supervisor.py')
    seed = module_from_spec(spec); spec.loader.exec_module(seed)
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine, tables=[model.__table__ for model in (AgentDefinition, AgentDefinitionRevision, SkillDefinition, SkillDefinitionRevision, ToolDefinitionOverride, KnowledgeBase, KnowledgeDocument, KnowledgeVersion, KnowledgeChunk, KnowledgeBinding)])
    with engine.begin() as conn, patch.object(seed.op, 'get_bind', return_value=conn):
        seed.upgrade(); seed.upgrade()
    with Session(engine, expire_on_commit=False) as db:
        yield db, db.query(AgentDefinition).filter_by(key=seed.SUPERVISOR['key']).one()
    engine.dispose()


class FakeProvider:
    def __init__(self, fail=False): self.fail = fail
    def generate_structured(self, system, content, **kwargs):
        if self.fail: raise RuntimeError('secret must never appear')
        if kwargs['kind'] == 'case_generation_review': return {'summary': '合成草稿已汇总', 'gaps': ['阈值待确认']}
        return {'cases': [{'title': '合成用例', 'priority': 'P1', 'requirement': '用户需求', 'preconditions': [], 'test_data': ['合成数据'], 'steps': ['检查输入'], 'expected_results': ['返回明确定义的结果'], 'coverage': ['正常路径'], 'needs_confirmation': []}]}


def invoke(db, main, modules, factory=None, **extra):
    body = GenerationRequest(project_id=1, requirements='合成评测需求', modules=modules, **extra)
    with patch('app.knowledge.service.access'), patch('app.agents.services.case_generation_service.get_project_or_404'), patch('app.agents.services.case_generation_service.resolve_authorized_model', side_effect=lambda *a, **kw: SimpleNamespace(id=kw.get('requested_model_id') or 10, model_name='synthetic')):
        return generate_case_suite(db, SimpleNamespace(id=1), main.id, body, provider_factory=factory or (lambda snapshot: FakeProvider()))


def test_supervisor_all_modules_and_seed_links(sandbox):
    db, main = sandbox
    assert db.query(AgentDefinition).count() == 6
    assert db.query(AgentDefinitionRevision).count() == 6
    assert db.query(SkillDefinition).count() == 6
    validate_agent_links(db, main.skill_keys, main.tool_keys, None, agent_enabled=True, child_agent_ids=main.child_agent_ids, workflow_template='case_generation')
    result = invoke(db, main, ['api','web','security','asr','ai'])
    assert result['status'] == 'COMPLETED'
    assert len(result['modules']) == 5
    assert not result['saved'] and not result['executed']
    assert all(item['model_config_id'] == 10 for item in result['modules'])
    assert result['review']['status'] == 'SUCCEEDED'


def test_partial_failure_and_main_review_failure_preserve_drafts(sandbox):
    db, main = sandbox
    result = invoke(db, main, ['api','asr'], lambda snapshot: FakeProvider(snapshot.get('module') == 'api'))
    assert result['status'] == 'PARTIAL_FAILED'
    assert result['modules'][1]['cases']
    assert 'secret' not in str(result)
    result = invoke(db, main, ['web'], lambda snapshot: FakeProvider('module' not in snapshot))
    assert result['status'] == 'PARTIAL_FAILED'
    assert result['modules'][0]['cases']


def test_enabled_scope_and_tools_are_enforced(sandbox):
    db, main = sandbox
    child = db.get(AgentDefinition, main.child_agent_ids[0])
    child.is_enabled = False
    with pytest.raises(HTTPException): invoke(db, main, ['api'])
    child.is_enabled = True
    db.add(ToolDefinitionOverride(tool_key='case_generation.generate_api', is_enabled=False, description='', parameter_overrides_json={}))
    db.flush()
    with pytest.raises(HTTPException): invoke(db, main, ['api'])
    with pytest.raises(HTTPException): invoke(db, main, ['api','api'])


def test_child_fixed_model_and_main_override(sandbox):
    db, main = sandbox
    child = db.get(AgentDefinition, main.child_agent_ids[0])
    child.settings_json = {'model_binding':'agent'}; child.model_config_id = 20
    result = invoke(db, main, ['api'], model_config_id=30)
    assert result['supervisor']['model_config_id'] == 30
    assert result['modules'][0]['model_config_id'] == 20
    main.settings_json = {'model_binding':'agent'}; main.model_config_id = 40
    with pytest.raises(HTTPException): invoke(db, main, ['web'], model_config_id=30)


def test_no_generation_tools_on_ordinary_analysis_children(sandbox):
    db, main = sandbox
    with pytest.raises(HTTPException):
        validate_agent_links(db, [], [], None, agent_enabled=True, child_agent_ids=main.child_agent_ids, workflow_template='api_test')
    child = db.get(AgentDefinition, main.child_agent_ids[0])
    with pytest.raises(HTTPException):
        validate_agent_links(db, child.skill_keys, [], None, agent_enabled=True, child_agent_ids=[], agent_id=child.id, workflow_template='case_generation')


def test_task_agent_option_contract_preserves_model_and_relationship():
    from app.orchestration.tasks.schemas import AvailableTaskAgentResponse
    row = AvailableTaskAgentResponse.model_validate({'id': 1, 'name': '主 Agent', 'description': '', 'workflow_template': 'api_test', 'version': 1,
        'model_config_id': 10, 'model_label': '合成主模型', 'child_agents': [{'id': 2, 'name': '子 Agent', 'version': 1, 'model_config_id': None, 'model_label': None}]})
    assert row.model_dump()['child_agents'][0]['name'] == '子 Agent'
    assert row.model_label == '合成主模型'
