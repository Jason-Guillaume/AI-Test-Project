"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from app.features.web_testing.services.case_inputs import case_response, load_steps, expand_steps, case_digest
from app.features.web_testing.services.response_mapper import json_dump

from app.features.web_testing.schemas import AuthInput, CaseInput, PageInput, PromoteInput, SessionStartInput
from app.features.web_testing.services.execution_service import artifact
from app.features.web_testing.services.case_service import bind_action
from app.agents.browser_authoring.services.session_service import close_session
from app.features.web_testing.services.case_service import confirm_case
from app.features.web_testing.services.execution_service import debug
from app.features.web_testing.services.auth_service import delete_auth
from app.features.web_testing.services.case_service import delete_case
from app.features.web_testing.services.page_service import delete_page
from app.features.web_testing.services.execution_service import environment_options
from app.features.web_testing.services.case_service import get_case
from app.agents.browser_authoring.services.session_service import get_session
from app.features.web_testing.services.execution_service import history
from app.features.web_testing.services.auth_service import list_auth
from app.features.web_testing.services.case_service import list_cases
from app.features.web_testing.services.page_service import list_pages
from app.agents.browser_authoring.services.session_service import list_sessions
from app.agents.browser_authoring.services.session_service import observe_session
from app.features.web_testing.services.promotion_service import promote_session
from app.agents.browser_authoring.services.session_service import record_agent_step
from app.features.web_testing.services.auth_service import save_auth
from app.features.web_testing.services.case_service import save_case
from app.features.web_testing.services.page_service import save_page
from app.agents.browser_authoring.services.session_service import start_session
from app.agents.browser_authoring.services.session_service import TaskBindingValidator
from app.features.web_testing.services.execution_service import trace_events


class WebUIService:
    """稳定领域门面；各资源由唯一实现持有。"""

    def list_pages(self, db, project_id, actor, *, page=1, page_size=200):
        """委托规范职责入口，保留调用契约。"""
        return list_pages(db, project_id, actor, page=page, page_size=page_size)

    def save_page(self, db, project_id, body: PageInput, actor, page_id=None):
        """委托规范职责入口，保留调用契约。"""
        return save_page(db, project_id, body, actor, page_id)

    def delete_page(self, db, page_id, actor):
        """委托规范职责入口，保留调用契约。"""
        return delete_page(db, page_id, actor)

    def list_cases(self, db, project_id, actor, *, page=1, page_size=20):
        """委托规范职责入口，保留调用契约。"""
        return list_cases(db, project_id, actor, page=page, page_size=page_size)

    def get_case(self, db, case_id, actor):
        """委托规范职责入口，保留调用契约。"""
        return get_case(db, case_id, actor)

    def save_case(self, db, project_id, body: CaseInput, actor, case_id=None, source_type='MANUAL'):
        """委托规范职责入口，保留调用契约。"""
        return save_case(db, project_id, body, actor, case_id, source_type)

    def confirm_case(self, db, case_id, revision, actor):
        """委托规范职责入口，保留调用契约。"""
        return confirm_case(db, case_id, revision, actor)

    def delete_case(self, db, case_id, actor):
        """委托规范职责入口，保留调用契约。"""
        return delete_case(db, case_id, actor)

    def list_auth(self, db, project_id, actor, *, page=1, page_size=200):
        """委托规范职责入口，保留调用契约。"""
        return list_auth(db, project_id, actor, page=page, page_size=page_size)

    def save_auth(self, db, project_id, body: AuthInput, actor, auth_id=None):
        """委托规范职责入口，保留调用契约。"""
        return save_auth(db, project_id, body, actor, auth_id)

    def delete_auth(self, db, auth_id, actor):
        """委托规范职责入口，保留调用契约。"""
        return delete_auth(db, auth_id, actor)

    def artifact(self, db, artifact_id, actor):
        """委托规范职责入口，保留调用契约。"""
        return artifact(db, artifact_id, actor)

    def debug(self, db, case_id, environment_id, actor):
        """委托规范职责入口，保留调用契约。"""
        return debug(db, case_id, environment_id, actor)

    def history(self, db, project_id, actor, *, case_id=None, page=1, page_size=20):
        """委托规范职责入口，保留调用契约。"""
        return history(db, project_id, actor, case_id=case_id, page=page, page_size=page_size)

    def bind_action(self, db, action_id, case_id, actor):
        """委托规范职责入口，保留调用契约。"""
        return bind_action(db, action_id, case_id, actor)

    def trace_events(self, db, artifact_id, actor):
        """委托规范职责入口，保留调用契约。"""
        return trace_events(db, artifact_id, actor)

    def environment_options(self, db, project_id, actor, keyword=''):
        """委托规范职责入口，保留调用契约。"""
        return environment_options(db, project_id, actor, keyword)


    def start_session(self, db, project_id, body: SessionStartInput, actor, *, task_run_id: int | None=None, task_agent_instance_id: int | None=None, task_binding_validator: TaskBindingValidator | None=None):
        """委托规范职责入口，保留调用契约。"""
        return start_session(
            db, project_id, body, actor,
            task_run_id=task_run_id,
            task_agent_instance_id=task_agent_instance_id,
            task_binding_validator=task_binding_validator,
        )

    def get_session(self, db, session_id, actor, *, task_run_id: int | None=None):
        """委托规范职责入口，保留调用契约。"""
        return get_session(db, session_id, actor, task_run_id=task_run_id)

    def list_sessions(self, db, project_id, actor, *, page=1, page_size=20):
        """委托规范职责入口，保留调用契约。"""
        return list_sessions(db, project_id, actor, page=page, page_size=page_size)

    def observe_session(self, db, session_id, actor, *, task_run_id: int | None=None):
        """委托规范职责入口，保留调用契约。"""
        return observe_session(db, session_id, actor, task_run_id=task_run_id)

    def record_agent_step(self, db, session_id, *, sort, step, result, status, actor):
        """委托规范职责入口，保留调用契约。"""
        return record_agent_step(db, session_id, sort=sort, step=step, result=result, status=status, actor=actor)

    def promote_session(self, db, session_id, body: PromoteInput, actor, *, task_run_id: int | None=None):
        """委托规范职责入口，保留调用契约。"""
        return promote_session(db, session_id, body, actor, task_run_id=task_run_id)

    def close_session(self, db, session_id, actor, *, task_run_id: int | None=None):
        """委托规范职责入口，保留调用契约。"""
        return close_session(db, session_id, actor, task_run_id=task_run_id)


__all__ = [
    'WebUIService',
    'case_response',
    'load_steps',
    'expand_steps',
    'case_digest',
    'json_dump',
]
