"""用例标题整理的纯函数测试。不连数据库。"""

from app.features.test_management.titles import optimize_case_title


def test_drop_unresolved_and_keep_code() -> None:
    """状态词退出标题，编号和动作保留。"""
    assert optimize_case_title("TC-AUTH-LOGIN-001 UNRESOLVED｜默认租户生成授权地址") == "TC-AUTH-LOGIN-001 默认租户生成授权地址"


def test_collapse_duplicated_code() -> None:
    """截断编号和完整编号叠在一起时只留完整编号。"""
    raw = "TC-03-ROLE- TC-03-ROLE-employee｜UNRESOLVED｜角色矩阵：employee"
    assert optimize_case_title(raw) == "TC-03-ROLE-employee 角色矩阵：employee"


def test_intent_label_uses_colon() -> None:
    """正向、逆向这类短标签用冒号接正文。"""
    raw = "BIZ-AUTH-001 正向｜启用租户的管理员完成后台登录并进入模板管理"
    assert optimize_case_title(raw) == "BIZ-AUTH-001 正向：启用租户的管理员完成后台登录并进入模板管理"


def test_clean_title_stays() -> None:
    """没有噪音的标题不再改写。"""
    raw = "TC-AUTH-001 default 租户飞书登录成功"
    assert optimize_case_title(raw) == raw


def test_pending_note_keeps_first_clause() -> None:
    """待确认说明只留第一句，并去掉套话。"""
    raw = "待确认：需产品确认 reviewer 在关闭开关时仍可混剪，以及角色变更生效时机；关联场景不得据文档直接判通过。"
    assert optimize_case_title(raw) == "待确认：reviewer 在关闭开关时仍可混剪，以及角色变更生效时机"
