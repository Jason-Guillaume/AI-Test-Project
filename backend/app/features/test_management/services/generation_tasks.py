"""将生成批次接入统一任务；模块 Run 隔离现有 Run 级租约。"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.agents.services.case_generation_service import prepare_case_suite
from app.core.config import settings
from app.core.http.errors import bad_request, conflict
from app.core.models.identity import User
from app.core.models.project import Project
from app.features.test_management.models.case_generation import CaseGenerationBatch
from app.features.test_management.schemas.generation import GenerationTaskRequest
from app.features.test_management.services.generation_service import GenerationService, modules_for
from app.features.test_management.services.scope_service import ScopeService
from app.agents.models import AgentDefinition, AgentDefinitionRevision, AgentSession
from app.orchestration.tasks.models import Task, TaskRun, TaskWorkItem, TaskWorkItemDependency, TaskEvent, TaskAgentInstance
from app.orchestration.tasks.services.state_service import append_event
from app.platform.projects.services.access_service import require_writable_project
from app.tools.builtin.case_generation.contracts import GenerationRequest

KINDS = {"CASE_GENERATE", "CASE_REVIEW"}
TERMINAL = {"SUCCEEDED", "SUCCEEDED_WITH_ISSUES", "FAILED", "CANCELLED"}
BATCH_STATE = {"SUCCEEDED": "COMPLETED", "SUCCEEDED_WITH_ISSUES": "PARTIAL_FAILED"}
service = GenerationService()


def resource_policy() -> dict:
    """从显式配置生成策略快照；数据库全局并发闸门仍是上限。"""
    return {
        "module_concurrency": settings.CASE_GENERATION_MODULE_CONCURRENCY,
        "project_concurrency": settings.CASE_GENERATION_PROJECT_CONCURRENCY,
        "user_concurrency": settings.CASE_GENERATION_USER_CONCURRENCY,
        "max_attempts": settings.CASE_GENERATION_MAX_ATTEMPTS,
        "retry_seconds": settings.CASE_GENERATION_RETRY_SECONDS,
        "module_timeout": settings.CASE_GENERATION_MODULE_TIMEOUT_SECONDS,
        "task_timeout": settings.CASE_GENERATION_TASK_TIMEOUT_SECONDS,
        "token_budget": settings.CASE_GENERATION_TOKEN_BUDGET,
    }


def batch_works(db: Session, batch: CaseGenerationBatch) -> list[TaskWorkItem]:
    """按 Task 找到全部模块与 Review 工作项，不依赖 JSON 数据库方言。"""
    parent = db.get(TaskRun, batch.task_run_id)
    return db.query(TaskWorkItem).join(TaskRun, TaskRun.id == TaskWorkItem.task_run_id).filter(
        TaskRun.task_id == parent.task_id, TaskWorkItem.kind.in_(KINDS),
    ).order_by(TaskWorkItem.sequence, TaskWorkItem.id).all()


def submit(db: Session, project_id: int, body: GenerationTaskRequest, actor: User):
    """不调用模型，在一个短事务中原子创建批次、任务、模块和依赖。"""
    require_writable_project(db, project_id, actor)
    # 用户锁使跨项目幂等请求与用户额度检查串行；项目锁只在提交期持有。
    db.query(User).filter(User.id == actor.id).with_for_update().one()
    db.query(Project).filter(Project.id == project_id).with_for_update().one()
    payload = {"project_id": project_id, **body.model_dump(exclude={"request_key"})}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    key = f"case-generation:{body.request_key}"
    prior = db.query(Task).filter_by(created_by=actor.id, request_key=key).first()
    if prior:
        if prior.request_digest != digest:
            raise conflict("相同幂等键已用于不同生成请求")
        parent = db.query(TaskRun).filter_by(task_id=prior.id).order_by(TaskRun.run_number.desc()).first()
        batch = db.query(CaseGenerationBatch).filter_by(task_run_id=parent.id).one()
        db.commit()
        return service._batch_response(db, batch)
    policy = resource_policy()
    active = db.query(Task).filter(Task.task_mode == "CASE_GENERATION", Task.status.notin_(TERMINAL))
    if active.filter(Task.project_id == project_id).count() >= policy["project_concurrency"]:
        raise conflict("项目生成任务额度已满，请等待或取消已有任务")
    if active.filter(Task.created_by == actor.id).count() >= policy["user_concurrency"]:
        raise conflict("用户生成任务额度已满，请等待或取消已有任务")
    if body.scope_node_id is not None:
        node = ScopeService()._node_in_project(db, body.scope_node_id, project_id)
        if node.direction != body.direction:
            raise bad_request("所选范围不属于该测试方向")
    supervisor = db.get(AgentDefinition, body.agent_id)
    if supervisor is None:
        raise bad_request("主 Agent 不存在")
    modules, notes = modules_for(body.direction, body.include_security, service._available_modules(db, supervisor))
    request = GenerationRequest(project_id=project_id, requirements=body.requirements, modules=modules,
                                cases_per_module=body.cases_per_module, model_config_id=body.model_config_id)
    main, children = prepare_case_suite(db, actor, body.agent_id, request)
    task = Task(project_id=project_id, created_by=actor.id, agent_definition_id=main['id'],
                title=f"{body.direction} 用例生成", goal=body.requirements, task_mode="CASE_GENERATION",
                request_key=key, request_digest=digest, status="QUEUED")
    db.add(task)
    db.flush()
    batch = CaseGenerationBatch(project_id=project_id, direction=body.direction, scope_node_id=body.scope_node_id,
        supervisor_agent_id=main['id'], supervisor_version=main['version'], supervisor_name=main['name'],
        model_config_id=main['model_config_id'], model_name=main['model_name'], requirements=body.requirements,
        modules_json=modules, status="QUEUED", module_errors_json=notes, created_by=actor.id)
    db.add(batch)
    db.flush()
    works = []
    instances = []
    trace_id = uuid4().hex
    deadline_at = datetime.now() + timedelta(seconds=policy['task_timeout'])
    for index, snapshot in enumerate([*children, main], 1):
        review = index == len(children) + 1
        run = TaskRun(task_id=task.id, run_number=index, created_by=actor.id, status="QUEUED",
            trace_id=trace_id, deadline_at=deadline_at,
            stage="CASE_REVIEW" if review else "CASE_GENERATION", goal_snapshot=body.requirements,
            input_snapshot={"batch_id": batch.id, "agent": snapshot, "supervisor": main,
                            "request": request.model_dump(), "policy": policy})
        db.add(run)
        db.flush()
        revision = db.query(AgentDefinitionRevision).filter_by(
            agent_definition_id=snapshot['id'], version=snapshot['version']).first()
        instance = TaskAgentInstance(task_run_id=run.id, instance_key='supervisor' if review else snapshot['module'],
            role='MAIN' if review else 'SUB_AGENT', display_name=snapshot['name'], status='QUEUED',
            agent_definition_revision_id=revision.id if revision else None,
            model_config_id=snapshot['model_config_id'],
            config_snapshot={key: snapshot[key] for key in ('id', 'name', 'version', 'model_config_id', 'model_name', 'model_revision')},
            skills_json=[skill['key'] for skill in snapshot['skills']],
            tool_allowlist_json=[snapshot['tool_key']] if snapshot.get('tool_key') else [])
        db.add(instance)
        db.flush()
        db.add(AgentSession(project_id=project_id, user_id=actor.id, title=snapshot['name'],
            task_run_id=run.id, task_agent_instance_id=instance.id, current_stage=run.stage))
        instances.append(instance)
        work = TaskWorkItem(task_run_id=run.id, work_key="review" if review else snapshot['module'],
            agent_instance_id=instance.id,
            kind="CASE_REVIEW" if review else "CASE_GENERATE", sequence=index,
            input_json={"batch_id": batch.id}, idempotency_key=f"case:{batch.id}:{index}",
            max_attempts=policy['max_attempts'])
        db.add(work)
        db.flush()
        if review:
            batch.task_run_id = run.id
            for child in works:
                db.add(TaskWorkItemDependency(work_item_id=work.id, depends_on_id=child.id))
        works.append(work)
        append_event(db, run, "generation.queued", {"batch_id": batch.id, "module": work.work_key,
            "trace_id": trace_id}, agent_instance_id=instance.id)
    # 最后创建的 Review Run 是已存在的协调根，不另建执行实体。
    for item in works:
        db.get(TaskRun, item.task_run_id).execution_root_run_id = run.id
    for instance in instances[:-1]:
        instance.parent_agent_instance_id = instances[-1].id
    service._audit(db, batch, None, "CREATE", actor, {"task_id": task.id, "run_id": run.id, "modules": modules})
    db.commit()
    return service._batch_response(db, batch)


def sync_batch(db: Session, batch: CaseGenerationBatch) -> None:
    """模块收尾、取消及恢复时在同一事务中汇总批次与公共任务状态。"""
    parent = db.get(TaskRun, batch.task_run_id)
    task = db.get(Task, parent.task_id)
    works = batch_works(db, batch)
    modules = [work for work in works if work.kind == "CASE_GENERATE"]
    review = next(work for work in works if work.kind == "CASE_REVIEW")
    cancelling = batch.status in {"CANCEL_REQUESTED", "CANCELLED"}
    if cancelling:
        done = all(work.status in TERMINAL for work in works)
        state = "CANCELLED" if done else "CANCEL_REQUESTED"
        parent.status = task.status = batch.status = state
        if done:
            parent.finished_at = datetime.now()
    elif review.status in TERMINAL:
        successes = sum(work.status == "SUCCEEDED" for work in modules)
        state = "SUCCEEDED" if successes == len(modules) and review.status == "SUCCEEDED" else "SUCCEEDED_WITH_ISSUES" if successes else "FAILED"
        parent.status = task.status = state
        parent.finished_at = datetime.now()
        batch.status = BATCH_STATE.get(state, state)
    else:
        batch.status = "RUNNING" if any(work.attempt_count for work in works) else "QUEUED"
        parent.status = task.status = batch.status
    notes = [note for note in batch.module_errors_json or [] if note.get('status') == 'SKIPPED']
    # 会话和实例以持久化工作项为准；历史未装配会话的批次仍保持兼容。
    for work in works:
        instance = db.get(TaskAgentInstance, work.agent_instance_id) if work.agent_instance_id else None
        if instance:
            instance.status = (parent.status if work.kind == 'CASE_REVIEW' else
                               'QUEUED' if work.status == 'PENDING' else work.status)
        session = db.query(AgentSession).filter_by(task_run_id=work.task_run_id).first()
        if session:
            status = parent.status if work.kind == 'CASE_REVIEW' else work.status
            session.status = ('COMPLETED' if status in {'SUCCEEDED', 'SUCCEEDED_WITH_ISSUES'} else
                              'FAILED' if status in {'FAILED', 'CANCELLED'} else 'ACTIVE')
    batch.module_errors_json = notes + [{"module": work.work_key, "status": "FAILED", "error": work.error_message or "生成失败",
        "error_code": work.error_code} for work in works if work.status == 'FAILED']


def task_status(db: Session, batch_id: int, actor: User) -> dict:
    """只返回任务身份、模块数值指标和白名单事件，不暴露快照或草稿正文。"""
    batch = service._visible_batch(db, batch_id, actor)
    if not batch.task_run_id:
        raise bad_request("该批次使用旧同步流程")
    parent = db.get(TaskRun, batch.task_run_id)
    works = batch_works(db, batch)
    run_ids = [work.task_run_id for work in works]
    events = db.query(TaskEvent).filter(TaskEvent.task_run_id.in_(run_ids)).order_by(TaskEvent.created_at, TaskEvent.id).all()
    return {"task_id": parent.task_id, "task_run_id": parent.id, "batch_id": batch.id, "status": batch.status,
        "execution_root_run_id": parent.execution_root_run_id or parent.id, "trace_id": parent.trace_id,
        # 尚无投影回执表时不把“配置启用”误报为“已经投影”。
        "observability_status": 'DISABLED' if not settings.LANGFUSE_ENABLED else 'UNVERIFIED',
        "deadline_at": parent.deadline_at,
        "run_status": db.get(Task, parent.task_id).status,
        "completed": sum(work.status in TERMINAL for work in works), "total": len(works),
        "modules": [{"work_item_id": work.id, "task_run_id": work.task_run_id, "module": work.work_key,
            "status": work.status, "started_at": work.claimed_at, "finished_at": work.finished_at,
            "attempts": work.attempt_count, "error_code": work.error_code, "error": work.error_message,
            "duration_ms": (work.output_json or {}).get('duration_ms'), "usage": (work.output_json or {}).get('usage'),
            "trace_id": (work.output_json or {}).get('trace_id') or db.get(TaskRun, work.task_run_id).trace_id,
            "agent_run_id": work.agent_instance_id,
            "agent_session_id": db.query(AgentSession.id).filter_by(task_run_id=work.task_run_id).scalar(),
            "agent_id": db.get(TaskRun, work.task_run_id).input_snapshot['agent']['id'],
            "agent_version": db.get(TaskRun, work.task_run_id).input_snapshot['agent']['version'],
            "model_config_id": db.get(TaskRun, work.task_run_id).input_snapshot['agent']['model_config_id'],
            "model_revision": db.get(TaskRun, work.task_run_id).input_snapshot['agent'].get('model_revision'),
        } for work in works],
        "events": [{"id": event.id, "run_id": event.task_run_id, "type": event.event_type,
            "created_at": event.created_at, "detail": {key: value for key, value in (event.payload or {}).items()
            if key in {'batch_id', 'module', 'work_item_id', 'kind', 'attempt', 'status', 'error_code', 'delay', 'trace_id', 'duration_ms', 'usage'}}}
            for event in events]}


def control(db: Session, batch_id: int, actor: User, action: str):
    """在批次锁内协作取消或只重试失败项，成功和已审核草稿始终保留。"""
    batch = service._writable_batch(db, batch_id, actor)
    if action != 'cancel':
        db.query(User).filter(User.id == batch.created_by).with_for_update().first()
        db.query(Project).filter(Project.id == batch.project_id).with_for_update().one()
    batch = db.query(CaseGenerationBatch).filter_by(id=batch.id).with_for_update().one()
    if not batch.task_run_id:
        raise bad_request("该批次使用旧同步流程")
    parent = db.get(TaskRun, batch.task_run_id)
    # 所有路径先锁 batch 再锁 run，避免与收尾形成反向锁序。
    runs = db.query(TaskRun).filter_by(task_id=parent.task_id).order_by(TaskRun.id).with_for_update().all()
    works = batch_works(db, batch)
    if action == 'cancel':
        if batch.status in {'COMPLETED', 'PARTIAL_FAILED', 'FAILED', 'CANCELLED'}:
            return service._batch_response(db, batch)
        batch.status = 'CANCEL_REQUESTED'
        for run in runs:
            work = next(work for work in works if work.task_run_id == run.id)
            if work.status == 'PENDING':
                work.status = run.status = 'CANCELLED'
                work.finished_at = run.finished_at = datetime.now()
            elif work.status == 'RUNNING':
                run.status = 'CANCEL_REQUESTED'
            append_event(db, run, 'generation.cancel_requested', {'batch_id': batch.id})
    else:
        if batch.status not in {'PARTIAL_FAILED', 'FAILED'}:
            raise conflict("只允许重试已结束任务中的失败项")
        retry = [work for work in works if work.status == 'FAILED']
        if not retry:
            raise conflict("没有失败项可重试")
        policy = parent.input_snapshot['policy']
        active = db.query(Task).filter(Task.task_mode == 'CASE_GENERATION', Task.status.notin_(TERMINAL), Task.id != parent.task_id)
        current_policy = resource_policy()
        if (active.filter(Task.project_id == batch.project_id).count() >= current_policy['project_concurrency']
                or active.filter(Task.created_by == batch.created_by).count() >= current_policy['user_concurrency']):
            raise conflict("生成任务额度已满，请等待或取消已有任务")
        # 限制整个工作项的总尝试次数，手动重试也不能无限绕过预算。
        if any(work.attempt_count >= settings.CASE_GENERATION_TOTAL_ATTEMPTS for work in works if work in retry or work.kind == 'CASE_REVIEW'):
            raise conflict("已达到生成总重试上限，请修复配置后提交新任务")
        for work in works:
            if work in retry or work.kind == 'CASE_REVIEW':
                work.status = 'PENDING'
                work.output_json = None
                work.finished_at = work.claimed_at = work.available_at = None
                work.error_code = work.error_message = None
                work.max_attempts = min(settings.CASE_GENERATION_TOTAL_ATTEMPTS, work.attempt_count + policy['max_attempts'])
                run = next(run for run in runs if run.id == work.task_run_id)
                run.status = 'QUEUED'
                run.deadline_at = datetime.now() + timedelta(seconds=current_policy['task_timeout'])
                run.finished_at = None
                run.error_code = run.error_message = None
                append_event(db, run, 'generation.retry_requested', {'batch_id': batch.id, 'module': work.work_key})
        batch.status = 'QUEUED'
        batch.review_summary = None
        batch.review_gaps_json = []
    service._audit(db, batch, None, 'CANCEL' if action == 'cancel' else 'REGENERATE', actor, {"task_run_id": parent.id})
    db.flush()
    sync_batch(db, batch)
    db.commit()
    return service._batch_response(db, batch)


def recover_generation(*, db_factory) -> int:
    """沿用过期租约恢复生成 Run；遵循 batch→run 锁序和总尝试上限。"""
    from app.orchestration.tasks.models import TaskAttempt
    db = db_factory()
    now = datetime.now()
    recovered = 0
    try:
        expired = (db.query(TaskRun.id, TaskRun.input_snapshot).join(Task, Task.id == TaskRun.task_id)
            .join(TaskWorkItem, TaskWorkItem.task_run_id == TaskRun.id).filter(
                Task.task_mode == 'CASE_GENERATION', TaskWorkItem.status.in_(('PENDING', 'RUNNING')),
                or_(TaskRun.lease_expires_at < now, TaskRun.deadline_at <= now)).all())
        db.rollback()
        for run_id, snapshot in expired:
            batch = db.query(CaseGenerationBatch).filter_by(id=snapshot['batch_id']).with_for_update().first()
            run = db.query(TaskRun).filter_by(id=run_id).with_for_update().populate_existing().first()
            current_time = datetime.now()
            deadline_expired = bool(run and run.deadline_at and run.deadline_at <= current_time)
            lease_expired = bool(run and run.lease_expires_at and run.lease_expires_at <= current_time)
            if not batch or not run or not (deadline_expired or lease_expired):
                db.rollback()
                continue
            work = db.query(TaskWorkItem).filter_by(task_run_id=run.id).one()
            attempt = db.query(TaskAttempt).filter_by(work_item_id=work.id, status='RUNNING').first()
            module_timeout = bool(attempt and attempt.deadline_at and attempt.deadline_at <= current_time)
            if attempt:
                attempt.status = 'FAILED' if module_timeout else 'INTERRUPTED'
                attempt.finished_at = now
                attempt.error_code = 'MODULE_TIMEOUT' if module_timeout else 'WORKER_INTERRUPTED'
            if run.status == 'CANCEL_REQUESTED' or batch.status == 'CANCEL_REQUESTED':
                work.status = run.status = 'CANCELLED'
                work.finished_at = run.finished_at = now
            elif deadline_expired:
                # 截止时间包含排队与退避；健康心跳也不能无限延长整个生成任务。
                work.status = run.status = 'FAILED'
                work.error_code = run.error_code = 'TASK_DEADLINE_EXCEEDED'
                work.error_message = run.error_message = '生成任务已超过总截止时间'
                work.finished_at = run.finished_at = now
            elif work.status == 'RUNNING' and work.attempt_count < work.max_attempts:
                work.status = 'PENDING'
                run.status = 'QUEUED'
                work.available_at = now + timedelta(seconds=snapshot['policy']['retry_seconds'] * 2 ** max(0, work.attempt_count - 1))
            elif work.status == 'RUNNING':
                work.status = run.status = 'FAILED'
                work.error_code = 'WORKER_RECOVERY_EXHAUSTED'
                work.error_message = 'Worker 多次中断，已达到自动恢复上限'
                work.finished_at = run.finished_at = now
            run.lease_owner = run.lease_expires_at = None
            append_event(db, run, 'run.recovered', {'batch_id': batch.id, 'work_item_id': work.id, 'status': work.status})
            db.flush()
            sync_batch(db, batch)
            db.commit()
            recovered += 1
        return recovered
    finally:
        db.close()
