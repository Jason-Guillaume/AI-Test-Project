"""把导入用例的标题收成可读名称。

对外只暴露 optimize_case_title。不访问数据库，也不改描述。
导入脚本和标题整理脚本都用它，避免两套规则把同一批标题写成不同样子。
状态词（如 UNRESOLVED）只从标题去掉，原文字仍留在描述的用例类型里。
"""

from __future__ import annotations

import re

# 这些词是导入时夹进来的状态，不是用例在测什么。
_STATUS_TOKENS = {"UNRESOLVED", "TBD", "TODO", "N/A", "NA", "PENDING", "UNKNOWN"}
# 短标签放在编号后面时，用冒号接正文，读起来像「正向：登录成功」。
_INTENT_LABELS = {"正向", "逆向", "异常", "边界", "权限", "安全", "功能"}
_PIPE_RE = re.compile(r"\s*[｜|]\s*")
_SPACE_RE = re.compile(r"[ \t]+")
# 编号被截断后，下一截又以同一编号开头，例如「TC-03-ROLE- TC-03-ROLE-admin」。
_DUP_CODE_RE = re.compile(r"([A-Z]{2,}(?:-[A-Za-z0-9]+)*-)\s+\1")
_PENDING_FILLER_RE = re.compile(r"^(待确认：)\s*(?:需产品确认|需确认|需要确认|需提供|需)\s*")
_TITLE_LIMIT = 200


def optimize_case_title(name: str) -> str:
    """收成「编号 + 在测什么」。

    给导入后的整理和再次导入用。已经干净的标题保持原样。
    空标题返回「未命名用例」，避免写入空名称。
    """
    text = _SPACE_RE.sub(" ", (name or "").replace("\n", " ")).strip()
    if not text:
        return "未命名用例"
    # 待确认条目往往是一整段说明，标题只留第一句。
    if text.startswith("待确认"):
        text = _SPACE_RE.sub(" ", _PENDING_FILLER_RE.sub(r"\1", text.split("；")[0].split(";")[0])).strip()
    previous = None
    while previous != text:
        previous = text
        text = _DUP_CODE_RE.sub(r"\1", text)
    parts = [_strip_status(part) for part in _PIPE_RE.split(text)]
    parts = [part for part in parts if part]
    if not parts:
        return "未命名用例"
    title = _join(parts)
    title = _SPACE_RE.sub(" ", title).strip()
    if len(title) <= _TITLE_LIMIT:
        return title or "未命名用例"
    return title[: _TITLE_LIMIT - 1] + "…"


def _strip_status(part: str) -> str:
    """去掉一段里单独成词的状态标记，保留前后的编号和中文。"""
    kept = [token for token in part.split(" ") if token.upper() not in _STATUS_TOKENS]
    return " ".join(kept).strip()


def _join(parts: list[str]) -> str:
    """编号和正文用空格接；短的测试意图用冒号接。"""
    if len(parts) == 1:
        return parts[0]
    head, *rest = parts
    tail = "：".join(rest)
    if head.endswith(("：", ":")):
        return f"{head}{tail}"
    if head.split(" ")[-1] in _INTENT_LABELS:
        return f"{head}：{tail}"
    return f"{head} {tail}"
