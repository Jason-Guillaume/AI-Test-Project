"""测试管理服务层共享的可见性 / 可写性校验与实体→项目回溯。

集中放在 feature 内部（services/_access.py）。按 §30 约束：测试模块**不**依赖
Business Service 私有实现，因此本文件直接基于 app.shared.roles 自建访问校验，
不 import app.features.business.services._access。稳定契约（ApiInterface.id /
BusinessFlow.id / BusinessAction.id / Environment.id / Project.id）通过 ORM 模型
读取使用，但不调用业务服务层方法。

权限口径与 defects / api_catalog / business 一致：
- 读：对该 project 至少 viewer；不可见与不存在共用 404（隐藏存在性）。
- 写：至少 member；不足 403（写操作语义上不存在「隐藏」，故用 403）。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.features.test_management.models.execution import TestRun
from app.features.test_management.models.test_case import TestCase
from app.features.test_management.models.test_plan import TestPlan
from app.features.test_management.models.test_point import TestPoint
from app.features.test_management.models.test_strategy import TestStrategy
from app.features.test_management.models.test_suite import TestSuite
from app.models.identity import User
from app.models.project import Project
from app.shared.errors import forbidden, not_found
from app.shared.roles import (
    PROJECT_ROLE_MEMBER,
    PROJECT_ROLE_VIEWER,
    has_project_role,
    project_role_for,
)


def get_project_or_404(db: Session, project_id: int, user: User) -> Project:
    """取项目并校验可见性（viewer+）；不可见与不存在共用 404。"""
    project = db.get(Project, project_id)
    if project is None:
        raise not_found("项目不存在")
    if not has_project_role(project_role_for(db, project, user), PROJECT_ROLE_VIEWER):
        raise not_found("项目不存在")
    return project


def check_writable(db: Session, project: Project, actor: User) -> None:
    """写操作权限校验：至少 project member，不足 403。"""
    role = project_role_for(db, project, actor)
    if not has_project_role(role, PROJECT_ROLE_MEMBER):
        raise forbidden("需要项目成员权限")


def require_writable_project(db: Session, project_id: int, user: User) -> Project:
    """取项目并校验可写（member+）；不可见 404，不可写 403。"""
    project = get_project_or_404(db, project_id, user)
    check_writable(db, project, user)
    return project


# ---------------------------------------------------------------- 实体 → 项目回溯
# 测试资产均直接存储 project_id（冗余），回溯无需联表。找不到实体一律 404，
# 避免上层把「实体不存在」误判成「无权」。回溯函数只解析 project_id，不做可见性校验。


def resolve_strategy_project_id(db: Session, strategy_id: int) -> int:
    strategy = db.get(TestStrategy, strategy_id)
    if strategy is None:
        raise not_found("测试策略不存在")
    return strategy.project_id


def resolve_point_project_id(db: Session, point_id: int) -> int:
    point = db.get(TestPoint, point_id)
    if point is None:
        raise not_found("测试点不存在")
    return point.project_id


def resolve_case_project_id(db: Session, case_id: int) -> int:
    case = db.get(TestCase, case_id)
    if case is None:
        raise not_found("测试用例不存在")
    return case.project_id


def resolve_suite_project_id(db: Session, suite_id: int) -> int:
    suite = db.get(TestSuite, suite_id)
    if suite is None:
        raise not_found("测试套件不存在")
    return suite.project_id


def resolve_plan_project_id(db: Session, plan_id: int) -> int:
    plan = db.get(TestPlan, plan_id)
    if plan is None:
        raise not_found("测试计划不存在")
    return plan.project_id


def resolve_run_project_id(db: Session, run_id: int) -> int:
    run = db.get(TestRun, run_id)
    if run is None:
        raise not_found("测试执行记录不存在")
    return run.project_id
