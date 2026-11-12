"""跨领域模板解析入口；只解释调用方提供的纯数据上下文。"""

from __future__ import annotations

from app.execution.templates.resolver import (
    MISSING,
    RequestContext,
    ResolveScope,
    resolve_template,
    resolve_token_str,
)


__all__ = [
    'MISSING',
    'RequestContext',
    'ResolveScope',
    'resolve_template',
    'resolve_token_str',
]
