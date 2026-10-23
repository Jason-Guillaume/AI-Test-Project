"""页面观测器：脱敏语义树与遮罩截图，供智能体决策与前端展示。

安全约束：
- 语义树来自 accessibility API（aria_snapshot），不包含原始 DOM 结构。
- 输入框值全部遮罩，避免凭据泄露。
- 已知密钥在文本和截图中均被替换。
- 截图遮罩所有输入元素和已知密钥文本。
- 不开启 tracing snapshots。
"""
from __future__ import annotations

import base64
import re
from urllib.parse import urlsplit, urlunsplit

from app.features.agent.providers.sanitizer import sanitize_text
from app.features.web_ui.runtime.playwright_executor import locate, scrub

# 遮罩选择器：所有输入、iframe、内容可编辑区、显式敏感元素
_MASK_SELECTORS = "input, textarea, iframe, [contenteditable=true], [data-sensitive]"

# 输入框值脱敏：textbox/searchbox/spinbutton/password 后的 : value 替换为占位符
_INPUT_ROLES = r"textbox|searchbox|spinbutton|password"
_INLINE_VALUE_PATTERN = re.compile(
    rf'(\b({_INPUT_ROLES})\s*(?:"[^"]*")?\s*:\s+)(\S[^\n]*)'
)
_TEXTBOX_MASKED = "******"

# 语义树大小上限（字符数），超出部分截断并标注
_TREE_MAX_CHARS = 60000


def _clean_url(url: str) -> str:
    """移除查询串与片段，仅保留协议、主机和路径。"""
    try:
        parsed = urlsplit(url)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    except Exception:
        return ""


def _mask_tree(text: str, secrets: list[str]) -> str:
    """脱敏语义树：遮罩输入框值、替换已知密钥、按值形态脱敏。"""
    # 1. 遮罩所有输入框的值（当前内容可能是凭据）
    text = _INLINE_VALUE_PATTERN.sub(lambda m: m.group(1) + _TEXTBOX_MASKED, text)
    # 2. 替换已知密钥值（精确匹配）
    text = scrub(text, secrets)
    # 3. 按值形态脱敏（webhook URL、URL 查询串中的凭证、secret 令牌串）
    text = sanitize_text(text)
    return text


def observe(page, *, secrets=None, sensitive_locators=None, timeout_ms=5000):
    """观察当前页面，返回脱敏语义树与遮罩截图。

    Args:
        page: Playwright Page 对象。
        secrets: 已知密钥列表，用于替换文本和截图中的精确值。
        sensitive_locators: 需要额外遮罩的定位器列表（WebStep.locator 格式）。
        timeout_ms: aria_snapshot 超时时间（毫秒）。

    Returns:
        dict: {url, title, accessibility_tree, screenshot_b64}
        - url: 清理后的页面 URL（无查询串和片段）
        - title: 脱敏后的页面标题
        - accessibility_tree: 脱敏后的语义树文本
        - screenshot_b64: 遮罩截图的 Base64 编码
    """
    secrets = list(secrets or [])
    result = {"url": "", "title": "", "accessibility_tree": "", "screenshot_b64": ""}

    # URL 和标题
    try:
        result["url"] = _clean_url(page.url)
        result["title"] = scrub(page.title(), secrets)
    except Exception as exc:
        result["url"] = f"error:{type(exc).__name__}"

    # 语义树
    try:
        tree = page.aria_snapshot(timeout=timeout_ms)
        tree = _mask_tree(tree, secrets)
        # 截断超大页面，避免 prompt 膨胀
        if len(tree) > _TREE_MAX_CHARS:
            tree = tree[:_TREE_MAX_CHARS] + f"\n...（语义树已截断，共 {len(tree)} 字符）"
        result["accessibility_tree"] = tree
    except Exception as exc:
        result["accessibility_tree"] = f"error:{type(exc).__name__}"

    # 遮罩截图
    try:
        masks = [page.locator(_MASK_SELECTORS)]
        if sensitive_locators:
            masks += [locate(page, loc) for loc in sensitive_locators]
        masks += [page.get_by_text(str(s), exact=False) for s in secrets if len(str(s)) >= 3]
        image = page.screenshot(mask=masks, timeout=3000, full_page=False)
        result["screenshot_b64"] = base64.b64encode(image).decode()
    except Exception:
        result["screenshot_b64"] = ""

    return result
