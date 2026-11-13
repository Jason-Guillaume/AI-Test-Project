"""Shared safety rules for Jenkins parameters and execution timeouts."""

from __future__ import annotations

import re
from typing import Mapping

MAX_EXECUTION_TIMEOUT_SECONDS = 10_800
MAX_CUSTOM_JENKINS_PARAMETERS = 50
PARAMETER_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
SENSITIVE_PARAMETER = re.compile(r"(?i)(secret|token|password|webhook|credential|api[_-]?key|private[_-]?key)")
_DANGEROUS_VALUE = re.compile(r"[\x00-\x1f\x7f;&|$`<>\\]")
RESERVED_JENKINS_PARAMETERS = frozenset({
    "AUTOMATION_EXECUTION_ID", "AUTOMATION_PROJECT_ID", "AUTOMATION_CALLBACK_KEY",
    "AUTOMATION_CALLBACK_URL", "AUTOMATION_HISTORY_URL", "AUTOMATION_PROVIDER",
    "REPOSITORY_URL", "REPOSITORY_ID", "BRANCH_NAME", "TEST_ENV", "PYTEST_ARGS",
    "TEST_TAGS", "TEST_SCOPE", "BUILD_TIMEOUT_MINUTES",
    "AUTOMATION_STATUS", "JENKINS_RESULT", "AUTOMATION_START_MS", "AUTOMATION_CALLBACK_SECRET",
    "AUTOMATION_CALLBACK_ORIGIN", "REPOSITORY_CREDENTIALS_ID", "CALLBACK_CREDENTIALS_ID",
    "BUILD_NUMBER", "BUILD_URL", "JOB_NAME", "JENKINS_URL", "WORKSPACE", "NODE_NAME",
    "EXECUTOR_NUMBER", "PATH", "HOME", "SHELL", "JAVA_HOME",
})


def validate_pipeline_parameters(
    values: Mapping[str, object] | None,
    *,
    reject_reserved: bool = False,
) -> dict[str, str]:
    """Validate custom CI parameters without logging or interpolating their values."""
    if values is None:
        return {}
    if not isinstance(values, Mapping):
        raise ValueError("自定义流水线参数必须是对象")
    if len(values) > MAX_CUSTOM_JENKINS_PARAMETERS:
        raise ValueError(f"自定义流水线参数不能超过 {MAX_CUSTOM_JENKINS_PARAMETERS} 项")

    clean: dict[str, str] = {}
    normalized_names: set[str] = set()
    for name, raw_value in values.items():
        if not isinstance(name, str) or not PARAMETER_NAME.fullmatch(name):
            raise ValueError("自定义参数名称格式不合法")
        normalized = name.upper()
        if normalized in normalized_names:
            raise ValueError("自定义参数名称不能仅大小写不同")
        normalized_names.add(normalized)
        if reject_reserved and normalized in RESERVED_JENKINS_PARAMETERS:
            raise ValueError(f"自定义参数名 {name} 为平台保留参数")
        if not isinstance(raw_value, str):
            raise ValueError(f"自定义参数 {name} 的值必须是字符串")
        if len(raw_value) > 2_000:
            raise ValueError(f"自定义参数 {name} 超过 2000 个字符")
        if _DANGEROUS_VALUE.search(raw_value):
            raise ValueError(f"自定义参数 {name} 含控制字符或命令分隔符")
        clean[name] = raw_value
    return clean
