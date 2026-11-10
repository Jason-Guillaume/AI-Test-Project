"""双维拆解纯函数测试（facets.py）。不连数据库。

对应 P1 整理脚本的三条规则：范围路径拆维、描述解析接口、路径归一化匹配。
"""

from app.features.test_management.facets import (
    clip,
    normalize_path,
    parse_endpoint,
    parse_scope_path,
    scope_path_of_point,
)


class TestParseScopePath:
    """范围路径拆成 对象 + 维度 + 叶子场景。"""

    def test_full_path(self) -> None:
        """三段路径拆出接口对象、边界维度和叶子场景。"""
        facets = parse_scope_path("接口测试 / 边界测试 / 登录接口")
        assert facets is not None
        assert facets.target_type == "API"
        assert facets.case_type == "BOUNDARY"
        assert facets.leaf == "登录接口"

    def test_ui_and_security(self) -> None:
        """UI 对象归 WEB，安全段认得出。"""
        facets = parse_scope_path("UI测试 / 安全测试 / 越权访问")
        assert facets is not None
        assert facets.target_type == "WEB"
        assert facets.case_type == "SECURITY"

    def test_missing_dimension(self) -> None:
        """只有对象和场景时维度为空，整理脚本不动 case_type。"""
        facets = parse_scope_path("接口测试 / 登录接口")
        assert facets is not None
        assert facets.target_type == "API"
        assert facets.case_type is None
        assert facets.leaf == "登录接口"

    def test_ai_target_fallback(self) -> None:
        """AI 词只在不命中其他对象词时兜底归 AI。"""
        facets = parse_scope_path("LangGraph 智能体专项测试范围 / 提示词注入")
        assert facets is not None
        assert facets.target_type == "AI"
        # 「AI 混剪前台」是界面、「AI 调用接口专项」是接口，都不归 AI。
        assert parse_scope_path("AI 混剪前台 / 登录页").target_type == "WEB"
        assert parse_scope_path("AI调用接口专项 / 超时重试").target_type == "API"

    def test_backend_words_map_to_api(self) -> None:
        """「后端」归接口对象，「后台」仍归界面（管理后台是页面）。"""
        assert parse_scope_path("PromoFlow后端测试范围（含AI专项） / 下单").target_type == "API"
        assert parse_scope_path("方小集后台 / 首页").target_type == "WEB"

    def test_slash_inside_leaf_kept(self) -> None:
        """场景名里的裸「/」不当分隔符，叶子不被截断。"""
        facets = parse_scope_path("AI 混剪前台｜任务列表 / 列表与分页 / 个人任务、加载/空态、分页")
        assert facets is not None
        assert facets.leaf == "个人任务、加载/空态、分页"

    def test_unknown_target(self) -> None:
        """认不出对象的路径不改数据。"""
        assert parse_scope_path("随便什么 / 登录") is None
        assert parse_scope_path("") is None

    def test_core_functional(self) -> None:
        """核心功能段归功能维度。"""
        facets = parse_scope_path("接口测试 / 核心功能测试 / 下单")
        assert facets is not None
        assert facets.case_type == "FUNCTIONAL"


class TestScopePathOfPoint:
    """范围路径优先取描述「路径：」行，退化用名字前缀。"""

    def test_description_wins(self) -> None:
        """名字带过去重后缀时，描述里的原始大纲更可靠。"""
        path = scope_path_of_point("范围·接口测试 / 登录·2", "路径：接口测试 / 登录\n备注：x")
        assert path == "接口测试 / 登录"

    def test_name_fallback(self) -> None:
        """没有描述时从名字去掉「范围·」前缀。"""
        assert scope_path_of_point("范围·UI测试 / 首页", None) == "UI测试 / 首页"

    def test_manual_point_ignored(self) -> None:
        """手工建的测试点没有范围痕迹，返回空串让脚本跳过。"""
        assert scope_path_of_point("登录主流程", "普通描述") == ""


class TestParseEndpoint:
    """从描述里解析 方法+路径。"""

    def test_module_path_line(self) -> None:
        """模块路径行能解析。"""
        desc = "画布：PromoFlow\n模块路径：POST /api/v1/projects\n用例类型：功能"
        assert parse_endpoint(desc) == ("POST", "/api/v1/projects")

    def test_canvas_line_fallback(self) -> None:
        """模块路径缺失时用画布行。"""
        assert parse_endpoint("画布：GET /healthz") == ("GET", "/healthz")

    def test_no_endpoint(self) -> None:
        """没有接口信息的描述返回 None。"""
        assert parse_endpoint("备注：纯 UI 点击") is None
        assert parse_endpoint(None) is None


class TestNormalizePath:
    """两侧路径归一化成同一形态再匹配。"""

    def test_template_and_digits_align(self) -> None:
        """{param} 模板和纯数字段归一后相等。"""
        assert normalize_path("/users/{user_id}") == normalize_path("/users/42")

    def test_query_and_trailing_slash(self) -> None:
        """查询串和尾斜杠不影响匹配。"""
        assert normalize_path("/users/?page=1") == normalize_path("/users")

    def test_clip(self) -> None:
        """超长名字截断带省略号。"""
        assert clip("x" * 300).endswith("…")
        assert len(clip("x" * 300)) == 200
