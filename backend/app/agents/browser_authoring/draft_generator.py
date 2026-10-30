"""Web 用例草稿候选生成；不保存正式资产，也不授予执行批准。"""

from __future__ import annotations

import json
from typing import Any


_SYSTEM = """你是测试开发平台的 Web UI 步骤生成助手。仅返回一个 JSON 对象：
{name,description,steps:[{name,operation,locator?,page_object_id?,element_key?,value?,assertion?,operator?,expected?,sensitive?}]}。
operation 仅 NAVIGATE/CLICK/FILL/SELECT/UPLOAD/WAIT/ASSERT；优先 TEST_ID、ROLE、LABEL、TEXT。
locator 为 {strategy,value,name?,exact?}。只引用提供的页面元素，不能猜测真实页面 DOM。
NAVIGATE 使用页面 path；密码只使用 ${data.auth_password} 且 sensitive=true。
禁止 Python、JavaScript、evaluate、脚本、SQL、命令、凭据和任意执行代码。只生成草稿，人工审核后执行。
"""


def generate_web_step_candidate(context: dict[str, Any], provider: Any) -> Any:
    """依据已脱敏的 Web/业务上下文生成结构化候选，不读取 ORM 或落库。"""
    return provider.generate_structured(
        _SYSTEM, json.dumps(context, ensure_ascii=False), kind="web_ui_steps",
    )
