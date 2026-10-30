"""纯路径读取和表达式比较基础能力，不执行业务规则或用户提供的代码。"""

from app.core.expressions.paths import extract_jsonpath, extract_dot_path

__all__ = ["extract_dot_path", "extract_jsonpath"]
