"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from app.features.security_testing.models import SecurityMutationRule
from app.features.security_testing.runtime import replay as replay_mod
from app.features.security_testing.runtime.types import MutationRuleView


_AUTH_HEADER_KEY = "authorization"


def parsed_body(raw: Any) -> Any:
    """把执行器返回的原始响应文本解析成 JSON；解析不了原样返回。

    断言层要读业务 ID、严重级别要判断是否泄露候选资源，都必须拿到结构化
    响应；执行器给的是文本。
    """
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return raw
    return raw


def single_outcome(result: Any) -> replay_mod.ReplayOutcome:
    """非重放变异的单次执行结果，形状与重放一致，断言层不用分叉。"""
    return replay_mod.ReplayOutcome(
        (int(getattr(result, "status_code", 0) or 0),),
        (getattr(result, "response_body", None),),
        (getattr(result, "error_message", None),),
    )


def auth_header_present(headers: dict[str, Any] | None) -> bool:
    """基线请求是否带了鉴权头（键名大小写不敏感）。"""
    return _AUTH_HEADER_KEY in {str(key).lower() for key in (headers or {})}


def fingerprint(*, api_id: Any, mutation_type: str, location: Any, field: Any, baseline_case_id: Any) -> str:
    """根据接口、变异类型、目标位置、目标字段和基线用例标识计算 SHA-256 指纹。"""
    raw = "|".join(str(v) for v in (api_id, mutation_type, location, field, baseline_case_id))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_evidence(
    *,
    rule_view: MutationRuleView,
    baseline_status: int | None,
    actual_status_codes: list[int],
    trace: list[dict[str, Any]],
    message: str,
    mutation_type: str,
    name: str | None,
) -> dict[str, Any]:
    """Finding 证据：只放脱敏后的状态码、trace 与固定中文结论。"""
    return {
        "mutation_type": mutation_type,
        "rule_name": name,
        "baseline_status": baseline_status,
        "actual_status_codes": actual_status_codes,
        "trace": trace,
        "message": message,
        "expected": {
            "expectation": rule_view.expected_security_behavior,
            "expected_status_codes": rule_view.expected_status_codes,
            "severity": rule_view.severity,
        },
    }


def rule_text(rule: SecurityMutationRule | None, field_name: str) -> str:
    """读规则上的中文文案字段，规则被删时返回空串。"""
    return str(getattr(rule, field_name, None) or "").strip()


def finding_title(name: str, mutation_type: str) -> str:
    """标题来自规则文案，不用 LLM 生成。"""
    return f"{name}（{mutation_type}）" if name else f"安全变异问题（{mutation_type}）"


def finding_description(description: str, message: str) -> str:
    """描述：规则的中文说明 + 本次实际判定结论。"""
    return f"{description}\n\n本次判定：{message}" if description else message


def finding_recommendation(mutation_type: str) -> str:
    """整改建议是固定模板文案：Phase 1 不做 LLM 发挥，也不自动建缺陷。"""
    if mutation_type in ("CROSS_USER", "IDOR", "RESOURCE_OWNER_CHANGE"):
        return "服务端读写资源时必须校验资源归属与调用方身份，不能只依赖前端隐藏入口。"
    if mutation_type == "ROLE_DOWNGRADE":
        return "服务端必须按会话里的真实角色重新判定权限，不要信任客户端传入的角色字段。"
    if mutation_type.startswith(
        ("REMOVE_TOKEN", "EMPTY_TOKEN", "INVALID_TOKEN", "MALFORMED", "WRONG_AUTH", "EXPIRED", "AUTHORIZATION")
    ):
        return "受保护接口在缺失或无效凭据时应当返回 401/403，不要放行匿名访问。"
    if mutation_type in ("REPLAY_SAME_REQUEST", "DUPLICATE_SUBMIT"):
        return "写入类接口应声明并校验幂等键，重复提交不应产生第二份业务数据。"
    if mutation_type.startswith(("REMOVE_FIELD", "NULL", "EMPTY", "TYPE_", "ZERO", "NEGATIVE", "OVER_MAX", "UNDER_MIN", "INVALID_")):
        return "服务端应按接口契约校验输入，非法输入应被拒绝而不是被静默接受。"
    return "服务端应按接口契约校验输入并在越权或非法输入时明确拒绝。"
