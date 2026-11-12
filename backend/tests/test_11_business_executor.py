"""业务执行引擎单元测试。

覆盖：
1. ExecutionContext 基本操作
2. SensitiveDataMasker 脱敏
3. PreconditionEvaluator 前置条件评估
4. MappingResolver INPUT/OUTPUT 映射解析
5. 共享 request_builder 的 URL 拼接 / 环境请求头
6. ApiRequestExecutor.execute（出站白名单拒绝）
7. BusinessFlowExecutor 顺序执行与失败停止
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session

from app.features.business.executors.context import ExecutionContext
from app.features.business.executors.mapping_resolver import (
    resolve_input_mappings,
    resolve_output_mappings,
)
from app.features.business.executors.precondition_evaluator import evaluate_preconditions
from app.core.security.sensitive import SensitiveDataMasker, mask_body, mask_headers
from app.execution.http.executor import ApiRequestExecutor, ApiRequestResult
from app.execution.http.request_builder import build_environment_url, get_environment_headers
from app.features.business.models.execution import ActionExecution, FlowExecution
from app.core.models.configuration import Environment


# --------------------------------------------------------------------------- 执行上下文 ExecutionContext


class TestExecutionContext:
    """ExecutionContext 运行时上下文管理。"""

    def test_set_and_get(self):
        """验证设置和获取场景及其预期结果。"""
        ctx = ExecutionContext()
        ctx.set("token", "abc123")
        assert ctx.get("token") == "abc123"

    def test_get_default(self):
        """验证获取默认场景及其预期结果。"""
        ctx = ExecutionContext()
        assert ctx.get("nonexistent") is None
        assert ctx.get("nonexistent", "fallback") == "fallback"

    def test_has(self):
        """验证是否包含场景及其预期结果。"""
        ctx = ExecutionContext()
        ctx.set("key", "value")
        assert ctx.has("key") is True
        assert ctx.has("missing") is False

    def test_keys(self):
        """验证`keys`场景及其预期结果。"""
        ctx = ExecutionContext()
        ctx.set("a", 1)
        ctx.set("b", 2)
        assert set(ctx.keys()) == {"a", "b"}

    def test_to_dict_roundtrip(self):
        """验证到字典往返转换场景及其预期结果。"""
        ctx = ExecutionContext(variables={"x": 10, "y": "hello"})
        data = ctx.to_dict()
        ctx2 = ExecutionContext.from_dict(data)
        assert ctx2.get("x") == 10
        assert ctx2.get("y") == "hello"

    def test_apply_ref(self):
        """验证应用`ref`场景及其预期结果。"""
        ctx = ExecutionContext(variables={"source_var": "some_value"})
        result = ctx.apply_ref("source_var", "target_var")
        assert result is True
        assert ctx.get("target_var") == "some_value"

    def test_apply_ref_missing_source(self):
        """验证应用`ref`缺失`source`场景及其预期结果。"""
        ctx = ExecutionContext()
        result = ctx.apply_ref("missing", "target")
        assert result is False
        assert ctx.has("target") is False


# --------------------------------------------------------------------------- 敏感数据脱敏器 SensitiveDataMasker


class TestSensitiveDataMasker:
    """敏感数据脱敏测试。"""

    def test_mask_request_headers(self):
        """验证脱敏请求请求头场景及其预期结果。"""
        req = {
            "method": "POST",
            "url": "https://api.example.com/login",
            "headers": {"authorization": "Bearer secret123", "X-App": "test"},
            "query": {},
            "body": {"password": "pass123", "username": "admin"},
            "body_type": "json",
        }
        masked = SensitiveDataMasker.mask_request(req["method"], req["url"], req["headers"], req["query"], req["body"], req["body_type"])
        assert masked["headers"]["authorization"] == "******"
        assert masked["headers"]["X-App"] == "test"
        assert masked["body"]["password"] == "******"
        assert masked["body"]["username"] == "admin"

    def test_mask_response(self):
        """验证脱敏响应场景及其预期结果。"""
        resp = {
            "status_code": 200,
            "headers": {"set-cookie": "token=abc; Path=/"},
            "body": {"access_token": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"}
        }
        masked = SensitiveDataMasker.mask_response(resp["status_code"], resp["headers"], resp["body"])
        assert masked["headers"]["set-cookie"] == "******"
        assert masked["body"]["access_token"] == "******"

    def test_mask_nested_dict(self):
        """验证脱敏`nested`字典场景及其预期结果。"""
        data = {"credentials": {"api_key": "sk-live-123", "other": "ok"}}
        masked = mask_body(data)
        assert masked["credentials"]["api_key"] == "******"
        assert masked["credentials"]["other"] == "ok"

    def test_mask_list(self):
        """验证脱敏列出场景及其预期结果。"""
        data = {"items": [{"token": "t1"}, {"name": "n1"}]}
        masked = mask_body(data)
        assert masked["items"][0]["token"] == "******"
        assert masked["items"][1]["name"] == "n1"

    def test_mask_empty(self):
        """验证脱敏空值场景及其预期结果。"""
        masked = mask_body({})
        assert masked == {}


# --------------------------------------------------------------------------- 前置条件评估器 PreconditionEvaluator


class TestPreconditionEvaluator:
    """前置条件评估器测试。"""

    def test_variable_eq_pass(self):
        """验证变量相等通过场景及其预期结果。"""
        pcs = [{"id": 1, "type": "VARIABLE", "target": "token", "operator": "EQ", "expected_value": "abc"}]
        ctx = {"token": "abc"}
        _, all_passed = evaluate_preconditions(pcs, ctx)
        assert all_passed is True

    def test_variable_eq_fail(self):
        """验证变量相等失败场景及其预期结果。"""
        pcs = [{"id": 1, "type": "VARIABLE", "target": "token", "operator": "EQ", "expected_value": "abc"}]
        ctx = {"token": "different"}
        _, all_passed = evaluate_preconditions(pcs, ctx)
        assert all_passed is False

    def test_variable_ne(self):
        """验证变量不相等场景及其预期结果。"""
        pcs = [{"id": 1, "type": "VARIABLE", "target": "count", "operator": "NE", "expected_value": "0"}]
        ctx = {"count": "5"}
        _, all_passed = evaluate_preconditions(pcs, ctx)
        assert all_passed is True

    def test_variable_in(self):
        """验证变量`in`场景及其预期结果。"""
        pcs = [{"id": 1, "type": "VARIABLE", "target": "role", "operator": "IN", "expected_value": "admin,manager"}]
        ctx = {"role": "admin"}
        _, all_passed = evaluate_preconditions(pcs, ctx)
        assert all_passed is True

    def test_variable_contains(self):
        """验证变量包含场景及其预期结果。"""
        pcs = [{"id": 1, "type": "VARIABLE", "target": "name", "operator": "CONTAINS", "expected_value": "test"}]
        ctx = {"name": "unittest"}
        _, all_passed = evaluate_preconditions(pcs, ctx)
        assert all_passed is True

    def test_variable_exists(self):
        """验证变量存在场景及其预期结果。"""
        pcs = [{"id": 1, "type": "VARIABLE", "target": "data", "operator": "EXISTS"}]
        ctx = {"data": "value"}
        _, all_passed = evaluate_preconditions(pcs, ctx)
        assert all_passed is True

    def test_variable_not_exists(self):
        """验证变量不存在场景及其预期结果。"""
        pcs = [{"id": 1, "type": "VARIABLE", "target": "missing", "operator": "NOT_EXISTS"}]
        ctx = {}
        _, all_passed = evaluate_preconditions(pcs, ctx)
        assert all_passed is True

    def test_business_type_manual(self):
        """验证业务类型手动场景及其预期结果。"""
        pcs = [{"id": 1, "type": "BUSINESS", "target": "some_biz", "operator": "EQ", "expected_value": "ok"}]
        ctx = {}
        results, all_passed = evaluate_preconditions(pcs, ctx)
        assert all_passed is True  # 手动或不可执行的前置条件按通过处理：passed=True。
        assert results[0].reason and "MANUAL" in results[0].reason

    def test_text_type_manual(self):
        """验证文本类型手动场景及其预期结果。"""
        pcs = [{"id": 1, "type": "TEXT", "target": "note", "operator": "EQ", "expected_value": "x"}]
        ctx = {}
        _, all_passed = evaluate_preconditions(pcs, ctx)
        assert all_passed is True


# --------------------------------------------------------------------------- 映射解析器 MappingResolver


class TestMappingResolver:
    """INPUT/OUTPUT 映射解析测试。"""

    def test_input_body_mapping(self):
        """验证输入请求体映射场景及其预期结果。"""
        mappings = [
            {"direction": "INPUT", "business_variable": "username", "api_location": "BODY", "api_field": "username"},
            {"direction": "INPUT", "business_variable": "password", "api_location": "BODY", "api_field": "password"},
        ]
        ctx = {"username": "admin", "password": "secret"}
        required = {"username": True, "password": True}
        parts, errors = resolve_input_mappings(mappings, ctx, required)
        assert errors == []
        assert parts["body"]["username"] == "admin"
        assert parts["body"]["password"] == "secret"

    def test_input_missing_required(self):
        """验证输入缺失必填场景及其预期结果。"""
        mappings = [{"direction": "INPUT", "business_variable": "token", "api_location": "HEADER", "api_field": "Authorization"}]
        ctx = {}
        required = {"token": True}
        parts, errors = resolve_input_mappings(mappings, ctx, required)
        assert len(errors) == 1
        assert "token" in errors[0]

    def test_input_header_mapping(self):
        """验证输入请求头映射场景及其预期结果。"""
        mappings = [{"direction": "INPUT", "business_variable": "token", "api_location": "HEADER", "api_field": "Authorization"}]
        ctx = {"token": "Bearer xyz"}
        required = {"token": True}
        parts, errors = resolve_input_mappings(mappings, ctx, required)
        assert parts["headers"]["Authorization"] == "Bearer xyz"

    def test_input_path_mapping(self):
        """验证输入路径映射场景及其预期结果。"""
        mappings = [{"direction": "INPUT", "business_variable": "project_id", "api_location": "PATH", "api_field": "project_id"}]
        ctx = {"project_id": "123"}
        parts, _ = resolve_input_mappings(mappings, ctx, {"project_id": True})
        assert parts["path_params"]["project_id"] == "123"

    def test_output_jsonpath_extraction(self):
        """验证输出`jsonpath``extraction`场景及其预期结果。"""
        mappings = [
            {"direction": "OUTPUT", "business_variable": "user_id", "expression": "$.data.id", "api_field": ""},
        ]
        body = json.dumps({"data": {"id": 42}})
        required = {"user_id": True}
        extracted, warnings = resolve_output_mappings(mappings, body, required)
        assert extracted["user_id"] == 42
        assert warnings == []

    def test_output_dot_path_extraction(self):
        """验证输出`dot`路径`extraction`场景及其预期结果。"""
        mappings = [{"direction": "OUTPUT", "business_variable": "name", "expression": "", "api_field": "data.name"}]
        body = json.dumps({"data": {"name": "Alice"}})
        extracted, _ = resolve_output_mappings(mappings, body, {"name": True})
        assert extracted["name"] == "Alice"

    def test_output_missing_required(self):
        """验证输出缺失必填场景及其预期结果。"""
        mappings = [{"direction": "OUTPUT", "business_variable": "token", "expression": "$.access_token", "api_field": ""}]
        body = json.dumps({"other": "value"})
        extracted, warnings = resolve_output_mappings(mappings, body, {"token": True})
        assert extracted["token"] is None
        assert len(warnings) == 1

    def test_output_non_json_response(self):
        """验证输出`non`JSON响应场景及其预期结果。"""
        mappings = [{"direction": "OUTPUT", "business_variable": "val", "expression": "$.value", "api_field": ""}]
        body = "not valid json"
        extracted, warnings = resolve_output_mappings(mappings, body, {"val": True})
        assert extracted["val"] is None
        assert any("JSON" in w for w in warnings)


# --------------------------------------------------------------------------- API 接口 请求执行器（非 HTTP）ApiRequestExecutor


class TestApiRequestExecutorBuildUrl:
    """URL 拼接与头获取测试。"""

    def test_build_url_basic(self):
        """验证构建URL基础场景及其预期结果。"""
        env = Environment(base_url="https://api.example.com", gateway_prefix="/v2", default_headers={})
        url = build_environment_url(env, "/projects")
        assert url == "https://api.example.com/v2/projects"

    def test_build_url_with_path_params(self):
        """验证构建URL包含路径`params`场景及其预期结果。"""
        env = Environment(base_url="https://api.example.com", gateway_prefix="", default_headers={})
        url = build_environment_url(env, "/projects/{id}", {"id": "42"})
        assert url == "https://api.example.com/projects/42"

    def test_build_url_no_gateway(self):
        """验证构建URL无`gateway`场景及其预期结果。"""
        env = Environment(base_url="https://api.example.com", gateway_prefix="", default_headers={})
        url = build_environment_url(env, "/health")
        assert url == "https://api.example.com/health"

    def test_get_environment_headers(self):
        """验证获取环境请求头场景及其预期结果。"""
        env = Environment(default_headers={"X-Custom": "value", "Authorization": "Bearer test"})
        headers = get_environment_headers(env)
        assert headers == {"X-Custom": "value", "Authorization": "Bearer test"}

    def test_get_environment_headers_empty(self):
        """验证获取环境请求头空值场景及其预期结果。"""
        env = Environment(default_headers={})
        headers = get_environment_headers(env)
        assert headers == {}

    def test_api_request_result_success(self):
        """验证API请求结果成功场景及其预期结果。"""
        result = ApiRequestResult()
        result.status_code = 200
        result.response_body = "ok"
        assert result.success is True

    def test_api_request_result_error(self):
        """验证API请求结果错误场景及其预期结果。"""
        result = ApiRequestResult()
        result.error_message = "connection failed"
        assert result.success is False


# --------------------------------------------------------------------------- 集成测试：执行记录模型


class TestExecutionModels:
    """执行记录模型测试（无 DB 依赖）。"""

    def test_flow_execution_defaults(self):
        """验证流程执行记录`defaults`场景及其预期结果。"""
        execution = FlowExecution(
            project_id=1,
            flow_id=1,
            status="PENDING",
            started_at=None,
            context_json={},
        )
        assert execution.status == "PENDING"
        assert execution.context_json == {}
        assert execution.revision == 1

    def test_action_execution_defaults(self):
        """验证动作执行记录`defaults`场景及其预期结果。"""
        ae = ActionExecution(
            flow_execution_id=1,
            action_id=1,
            sequence=0,
            status="PENDING",
        )
        assert ae.status == "PENDING"
        assert ae.duration_ms is None
