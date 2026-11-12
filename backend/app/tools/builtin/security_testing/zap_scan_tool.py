"""Agent Tool 层：ZAP 安全扫描（Phase 2，§二十三）。

与 `security_tool` 同范式的薄封装，只做两件事：把 `zap.job_service` 的结果转成可进
prompt 的 dict，以及保证权限与授权边界由 service 自己校验。

**核心约束（§二十三「主动扫描必须由后端校验到真实的人类批准行为」）**：

- LLM 只能**读**与**计划**。`preview_scan` 走 `job_service.plan`——纯读取，
  不写库、不发起任何 ZAP 网络请求。
- **不提供任何「让 LLM 创建任务」的工具**。创建任务的唯一入口是
  `create_scan_job(..., human_approved=True)`，而 `human_approved` 只有
  `zap_scan_job_creator_node` 能置真——那个节点只由人工 `confirm_security_scan`
  action 触发（router 按 action 路由，LLM 的工具参数里没有这个开关）。
- 即使 LLM 幻觉出一个 `confirmed=true`，`job_service.create` 仍会独立校验
  权限、环境、目标授权、确认与批准说明五关。LLM 的确认**不具备**授权效力。

刻意不提供：创建或修改扫描目标/策略、扩大扫描范围、绕过范围限制、执行破坏性动作、
把 Token / 凭据写进 prompt。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.features.security_testing.zap.schemas import ScanJobCreate
from app.features.security_testing.zap.services import job_service, profile_service, target_service
from app.core.models.identity import User

__all__ = [
    "list_scan_targets",
    "list_scan_profiles",
    "preview_scan",
    "create_scan_job",
    "NOT_HUMAN_APPROVED",
]

#: 工具层自设的硬失败码：任何非人工路径创建扫描任务都被直接拒绝。
NOT_HUMAN_APPROVED = "SCAN_JOB_NOT_HUMAN_APPROVED"

#: 目标摘要：足够 LLM 选目标，但不把 allowed_hosts / include_paths 塞进 prompt
#: （那些是范围配置，进 prompt 容易诱导 LLM 去"优化"范围）。
_TARGET_BRIEF_FIELDS = (
    "id", "name", "target_type", "base_url", "environment_id", "enabled",
    "authorization_status", "active_scan_allowed", "is_production",
)

#: 策略摘要：不含 selected_rule_ids / 路径清单。
_PROFILE_BRIEF_FIELDS = (
    "id", "name", "code", "is_builtin", "scan_mode", "is_active_scan", "enabled",
    "authentication_profile_id", "max_duration", "max_depth", "max_concurrency",
)

#: 计划摘要里保留的字段：limitations 是最重要的一段，必须完整保留。
_PLAN_BRIEF_FIELDS = (
    "is_active_scan", "production_blocked", "zap_available", "authentication_mode",
    "browser_session_established", "limitations", "estimated_requests",
    "max_duration_minutes", "max_depth", "max_concurrency", "request_delay_ms",
    "warning",
)


def _pick(obj: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """按字段白名单取值（service 增列不会漏出额外字段）。"""
    return {field: obj.get(field) for field in fields}


def list_scan_targets(db: Session, project_id: int, user: User) -> list[dict[str, Any]]:
    """本项目可用的扫描目标（含授权状态），供 LLM 选 `target_id`。"""
    response = target_service.list_targets(db, project_id, user, page=1, page_size=200)
    return [_pick(item.model_dump(mode="json"), _TARGET_BRIEF_FIELDS) for item in response.items]


def list_scan_profiles(db: Session, project_id: int, user: User) -> list[dict[str, Any]]:
    """本项目可用的扫描策略（平台内置 + 本项目自定义），供 LLM 选 `scan_profile_id`。"""
    response = profile_service.list_profiles(db, project_id, user, page=1, page_size=200)
    return [_pick(item.model_dump(mode="json"), _PROFILE_BRIEF_FIELDS) for item in response.items]


def preview_scan(
    db: Session,
    project_id: int,
    user: User,
    *,
    target_id: int,
    scan_profile_id: int,
    test_run_id: int | None = None,
) -> dict[str, Any]:
    """生成扫描计划预览：纯读取，不写库、不发 ZAP 请求。

    `confirmed` 恒为 False——预览阶段不存在"已批准"的概念，把批准状态留在预览里
    会让前端或 LLM 误以为已经拿到授权。
    """
    payload = ScanJobCreate(
        target_id=target_id,
        scan_profile_id=scan_profile_id,
        test_run_id=test_run_id,
        confirmed=False,
    )
    plan = job_service.plan(db, project_id, user, payload)
    data = plan.model_dump(mode="json")
    target = data.get("target") or {}
    profile = data.get("profile") or {}
    return {
        **_pick(data, _PLAN_BRIEF_FIELDS),
        "target": _pick(target, ("id", "name", "base_url", "authorization_status")),
        "profile": _pick(profile, ("id", "name", "scan_mode", "is_active_scan")),
        "environment": data.get("environment"),
        "exclude_paths": data.get("exclude_paths"),
    }


def create_scan_job(
    db: Session,
    project_id: int,
    user: User,
    *,
    target_id: int,
    scan_profile_id: int,
    human_approved: bool,
    approval_note: str | None = None,
    test_run_id: int | None = None,
) -> dict[str, Any]:
    """创建一个扫描任务。

    `human_approved=False` 时**直接抛错**，连 service 都不进——这是工具层的第一道闸，
    让"LLM 自己批准自己"在调用点就可见，而不是混在后面的业务校验里。
    主动扫描的完整授权（权限 / 环境 / 目标授权 / 确认 / 批准说明）仍由
    `job_service.create` 独立校验，不依赖本工具的参数。
    """
    if not human_approved:
        raise ValueError(f"{NOT_HUMAN_APPROVED}：创建扫描任务必须来自人工确认动作")

    payload = ScanJobCreate(
        target_id=target_id,
        scan_profile_id=scan_profile_id,
        test_run_id=test_run_id,
        confirmed=True,
        approval_note=approval_note,
    )
    row = job_service.create(db, project_id, user, payload)
    return job_service.to_read(db, row).model_dump(mode="json")


from app.tools.registry import bind_module_handlers

bind_module_handlers(globals(), {
    'list_scan_targets': ('runtime.security.list_scan_targets', 'read'),
    'list_scan_profiles': ('runtime.security.list_scan_profiles', 'read'),
    'preview_scan': ('runtime.security.preview_scan', 'write'),
    'create_scan_job': ('runtime.security.create_scan_job', 'high_risk'),
})
