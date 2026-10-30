"""OpenAI 兼容 Provider：以 httpx 调用模型端点。

- ProductionLLMProvider：从 model_configuration 公开配置契约读取启用配置并调用兼容接口；
  统一任务显式传入已授权候选链，结构化响应在切换下一候选前可执行 Pydantic 校验。
- FakeLLMProvider：按 kind 返回固定结构化 JSON，测试用，不依赖网络/密钥。

凭据解密、加密配置和资源授权仍由 model_configuration 与调用方持有；此处不依赖 Agent 图或领域工作流。
无默认模型配置时报 NO_DEFAULT_MODEL；原默认模型与显式授权候选链行为保持。
"""

from __future__ import annotations

import json
from typing import Any, Callable

import httpx
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.llm.tracing import llm_generation, update_generation
from app.core.security.sanitizer import build_chat_messages
from app.platform.model_configuration.services.model_config_service import load_model_for_provider
from app.llm.contracts import LLMError, LLMProvider


class ProductionLLMProvider:
    """生产 LLM Provider：按显式配置或默认配置调用 OpenAI 兼容接口。"""

    def __init__(
        self, db: Session, model_config_id: int | None = None, *,
        model_config_ids: list[int] | None = None,
        attempt_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        """保存数据库会话、授权后的候选模型和审计回调；不复制或输出加密凭据。"""
        self.db = db
        self.model_config_id = model_config_id
        self.explicit_route = model_config_ids is not None
        self.model_config_ids = list(dict.fromkeys(model_config_ids or []))
        self.attempt_callback = attempt_callback
        self.last_attempts: list[dict[str, Any]] = []
        self.last_model_config_id: int | None = None

    def generate_structured(
        self, system: str, user_content: str, schema: dict[str, Any] | None = None,
        *, kind: str | None = None, history: list[dict[str, str]] | None = None,
        validator: Callable[[dict[str, Any]], Any] | None = None,
    ) -> dict[str, Any]:
        """请求 JSON 结构化结果，并在候选模型之间复用同一提示与类型校验。"""
        messages = build_chat_messages(system, user_content, history=history)
        return self._call_candidates(messages, f"generate_structured.{kind or 'unknown'}", structured=True, validator=validator)

    def generate_structured_with_tools(
        self,
        system: str,
        user_content: str,
        *,
        tools: list[dict[str, Any]],
        tool_executor: Callable[[str, dict[str, Any]], Any],
        kind: str,
        validator: Callable[[dict[str, Any]], Any] | None = None,
    ) -> dict[str, Any]:
        """运行有次数上限的 OpenAI 兼容工具调用循环，最终仍须返回合法结构化结果。"""
        if not tools:
            return self.generate_structured(system, user_content, kind=kind, validator=validator)
        base_messages = build_chat_messages(system, user_content)
        failures: list[dict[str, Any]] = []
        last_error: LLMError | None = None
        for index, model_id in enumerate(self._candidate_model_ids()):
            cfg = None
            messages: list[dict[str, Any]] = [dict(item) for item in base_messages]
            try:
                cfg = self._load_config(model_id)
                api_key = cfg.api_key
                headers = {"Content-Type": "application/json"}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"
                final_content = ""
                usage: dict[str, Any] | None = None
                total_tool_calls = 0
                with llm_generation(
                    name=f"agent.generate_structured.{kind}",
                    model=cfg.model_name,
                    input_messages=base_messages,
                    model_parameters={"temperature": float(cfg.temperature or 0.2), "max_tokens": int(cfg.max_tokens or 4096)},
                ) as gen:
                    for _ in range(6):
                        body = {
                            "model": cfg.model_name,
                            "messages": messages,
                            "temperature": float(cfg.temperature or 0.2),
                            "max_tokens": int(cfg.max_tokens or 4096),
                            "tools": tools,
                            "tool_choice": "auto",
                        }
                        try:
                            response = httpx.post(
                                f"{cfg.api_base.rstrip('/')}/chat/completions",
                                json=body,
                                headers=headers,
                                timeout=float(cfg.timeout or 60),
                            )
                        except httpx.HTTPError as exc:
                            raise LLMError("LLM_TRANSPORT_ERROR", f"模型服务请求失败：{type(exc).__name__}", retryable=True) from exc
                        if response.status_code >= 400:
                            retryable = response.status_code == 429 or response.status_code >= 500
                            raise LLMError(
                                "LLM_RATE_LIMITED" if response.status_code == 429 else "LLM_PROVIDER_ERROR",
                                f"模型服务返回 HTTP {response.status_code}", retryable=retryable,
                            )
                        if len(response.content) > 2_000_000:
                            raise LLMError("STRUCTURED_OUTPUT_INVALID", "模型响应超过 2 MB 限制", retryable=True)
                        try:
                            data = response.json()
                            message = data["choices"][0]["message"]
                        except (ValueError, KeyError, IndexError, TypeError) as exc:
                            raise LLMError("STRUCTURED_OUTPUT_INVALID", "模型响应格式无法解析", retryable=True) from exc
                        usage = data.get("usage")
                        calls = message.get("tool_calls") or []
                        if not calls:
                            final_content = str(message.get("content") or "")
                            break
                        total_tool_calls += len(calls)
                        if total_tool_calls > 8:
                            raise LLMError("TOOL_CALL_LIMIT", "模型超过 8 次工具调用限制", retryable=True)
                        # 仅把经过本地 schema 与授权表映射的工具名交给 executor。
                        messages.append({
                            "role": "assistant",
                            "content": message.get("content"),
                            "tool_calls": calls,
                        })
                        for call in calls:
                            function = call.get("function") or {}
                            function_name = function.get("name")
                            try:
                                arguments = json.loads(function.get("arguments") or "{}")
                                if not isinstance(arguments, dict):
                                    raise ValueError("参数必须是 JSON 对象")
                                result = tool_executor(str(function_name or ""), arguments)
                                tool_result = {"ok": True, "result": result}
                            except Exception as exc:  # noqa: BLE001 — 工具错误不暴露内部地址或凭据。
                                tool_result = {"ok": False, "error": f"工具调用失败：{type(exc).__name__}"}
                            messages.append({
                                "role": "tool",
                                "tool_call_id": str(call.get("id") or "")[:120],
                                "content": json.dumps(tool_result, ensure_ascii=False, default=str)[:24_000],
                            })
                    else:
                        raise LLMError("TOOL_CALL_LIMIT", "模型超过工具调用轮数限制", retryable=True)
                    output = self._parse_json_content(final_content)
                    if validator is not None:
                        try:
                            validator(output)
                        except ValidationError as exc:
                            raise LLMError("STRUCTURED_OUTPUT_INVALID", "模型输出未通过任务结构校验", retryable=True) from exc
                    update_generation(gen, output=final_content, usage=usage)
                self._record_attempt(failures, model_id, cfg.model_name, index, "SUCCEEDED", None)
                self.last_attempts = failures
                self.last_model_config_id = cfg.id
                return output
            except LLMError as exc:
                last_error = exc
                self._record_attempt(failures, model_id, cfg.model_name if cfg else None, index, "FAILED", exc.code)
        self.last_attempts = failures
        if not self.explicit_route and last_error is not None:
            raise last_error
        raise LLMError("LLM_FALLBACK_EXHAUSTED", "主模型及已配置备用模型均不可用", retryable=True, attempts=failures)

    def chat(
        self, system: str, user_content: str,
        *, history: list[dict[str, str]] | None = None,
    ) -> str:
        """请求普通文本；显式任务路由失败时按候选顺序切换模型。"""
        messages = build_chat_messages(system, user_content, history=history)
        return self._call_candidates(messages, "chat", structured=False)

    def _call_candidates(
        self, messages: list[dict[str, str]], kind: str, *, structured: bool,
        validator: Callable[[dict[str, Any]], Any] | None = None,
    ) -> Any:
        """逐个尝试已授权模型；候选结果解析或类型校验失败时继续降级。"""
        failures: list[dict[str, Any]] = []
        last_error: LLMError | None = None
        candidates = self._candidate_model_ids()
        for index, model_id in enumerate(candidates):
            cfg = None
            try:
                cfg = self._load_config(model_id)
                api_key = cfg.api_key
                body: dict[str, Any] = {
                    "model": cfg.model_name,
                    "messages": messages,
                    "temperature": float(cfg.temperature or 0.2),
                    "max_tokens": int(cfg.max_tokens or 4096),
                }
                if structured:
                    body["response_format"] = {"type": "json_object"}
                headers = {"Content-Type": "application/json"}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"
                # 每个模型单独建 generation，便于追踪实际接手者且不混淆失败尝试。
                with llm_generation(
                    name=f"agent.{kind}", model=cfg.model_name, input_messages=messages,
                    model_parameters={"temperature": body["temperature"], "max_tokens": body["max_tokens"]},
                ) as gen:
                    try:
                        resp = httpx.post(
                            f"{cfg.api_base.rstrip('/')}/chat/completions", json=body, headers=headers,
                            timeout=float(cfg.timeout or 60),
                        )
                    except httpx.HTTPError as exc:
                        raise LLMError("LLM_TRANSPORT_ERROR", f"模型服务请求失败：{type(exc).__name__}", retryable=True) from exc
                    if resp.status_code >= 400:
                        retryable = resp.status_code == 429 or resp.status_code >= 500
                        raise LLMError(
                            "LLM_RATE_LIMITED" if resp.status_code == 429 else "LLM_PROVIDER_ERROR",
                            f"模型服务返回 HTTP {resp.status_code}", retryable=retryable,
                        )
                    try:
                        data = resp.json()
                        content = data["choices"][0]["message"]["content"]
                    except (ValueError, KeyError, IndexError, TypeError) as exc:
                        raise LLMError("STRUCTURED_OUTPUT_INVALID", "模型响应格式无法解析", retryable=True) from exc
                    output = self._parse_json_content(content) if structured else content
                    if structured and validator is not None:
                        try:
                            validator(output)
                        except ValidationError as exc:
                            raise LLMError("STRUCTURED_OUTPUT_INVALID", "模型输出未通过任务结构校验", retryable=True) from exc
                    update_generation(gen, output=content, usage=data.get("usage"))
                self._record_attempt(failures, model_id, cfg.model_name, index, "SUCCEEDED", None)
                self.last_attempts = failures
                self.last_model_config_id = cfg.id
                return output
            except LLMError as exc:
                last_error = exc
                self._record_attempt(failures, model_id, cfg.model_name if cfg else None, index, "FAILED", exc.code)

        self.last_attempts = failures
        # 显式任务路由只在所有候选均失败后返回可恢复错误，由持久化调度器安排下一轮。
        # 旧 Agent/报告调用未提供授权路由，保持其单模型错误码与原有失败语义。
        if not self.explicit_route and last_error is not None:
            raise last_error
        raise LLMError("LLM_FALLBACK_EXHAUSTED", "主模型及已配置备用模型均不可用", retryable=True, attempts=failures)

    def _record_attempt(
        self, failures: list[dict[str, Any]], model_id: int, model_name: str | None,
        index: int, status: str, error_code: str | None,
    ) -> None:
        """只记录模型身份、顺序和结果，避免把提示词或密钥写入任务事件。"""
        item = {
            "model_config_id": model_id, "model_name": model_name,
            "candidate_index": index, "status": status, "error_code": error_code,
        }
        failures.append(item)
        if self.attempt_callback is not None:
            self.attempt_callback(item)

    def _candidate_model_ids(self) -> list[int | None]:
        """返回调用方筛选并授权的模型顺序；兼容旧 Agent 的单模型绑定。"""
        if self.model_config_ids:
            return list(self.model_config_ids)
        return [self.model_config_id]

    def _load_config(self, model_config_id: int | None) -> Any:
        """解析单个已启用候选；任务层会在进入 Provider 前完成逐模型授权。"""
        cfg = load_model_for_provider(self.db, model_config_id)
        if cfg is None:
            if model_config_id is None:
                raise LLMError("NO_DEFAULT_MODEL", "未配置启用的默认模型，无法调用 LLM")
            raise LLMError("MODEL_UNAVAILABLE", "模型配置不存在或已停用", retryable=True)
        return cfg

    @staticmethod
    def _parse_json_content(content: str) -> dict[str, Any]:
        """模型可能返回带 ```json 围栏或多余文本，尽力抽取首个 JSON 对象。"""
        text = (content or "").strip()
        if not text:
            raise LLMError("STRUCTURED_OUTPUT_INVALID", "模型返回空内容")
        try:
            value = json.loads(text)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass
        # 退而抽取首个 {...} 片段。
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                value = json.loads(text[start : end + 1])
                if isinstance(value, dict):
                    return value
            except json.JSONDecodeError as exc:
                raise LLMError("STRUCTURED_OUTPUT_INVALID", f"模型输出非合法 JSON：{exc}") from exc
        raise LLMError("STRUCTURED_OUTPUT_INVALID", "模型输出未包含 JSON 对象")


class FakeLLMProvider:
    """测试用桩：按 kind 返回固定结构化 JSON，绝不发起网络请求。

    通过 set_response(kind, payload) 注入期望产出；未设置时用内置默认样例。
    """

    def __init__(self) -> None:
        """初始化对象状态。"""
        self._responses: dict[str, dict[str, Any]] = {}
        # 记录每次结构化调用的 (system, user_content, kind)，供测试断言敏感数据未泄入。
        self.calls: list[dict[str, Any]] = []

    def set_response(self, kind: str, payload: dict[str, Any]) -> None:
        """设置响应。"""
        self._responses[kind] = payload

    def generate_structured(
        self, system: str, user_content: str, schema: dict[str, Any] | None = None,
        *, kind: str | None = None, history: list[dict[str, str]] | None = None,
        validator: Callable[[dict[str, Any]], Any] | None = None,
    ) -> dict[str, Any]:
        """返回测试用结构化内容，并复用生产 Provider 的类型校验回调。"""
        self.calls.append({"system": system, "user": user_content, "kind": kind, "history": history or []})
        if kind and kind in self._responses:
            output = self._responses[kind]
        else:
            output = _DEFAULT_FAKE.get(kind or "default", {"result": "ok"})
        if validator is not None:
            validator(output)
        return output

    def chat(
        self, system: str, user_content: str,
        *, history: list[dict[str, str]] | None = None,
    ) -> str:
        """调用已配置的 LLM 提供器生成聊天回复。"""
        self.calls.append({"system": system, "user": user_content, "kind": "chat", "history": history or []})
        return "（FakeLLM 回复）测试桩不产生真实内容。"

    @property
    def last_call(self) -> dict[str, Any] | None:
        """返回最近一次模型调用记录。"""
        return self.calls[-1] if self.calls else None


# 内置默认样例：覆盖生成链各节点，确保 FakeLLMProvider 未显式注入时也能跑通 happy path。
_DEFAULT_FAKE: dict[str, dict[str, Any]] = {
    "intent": {
        "intent": "GENERATE_TEST_POINTS",
        "target_type": "API",
        "target_ids": [],
        "target_description": "测试目标接口",
        "clarify_question": None,
    },
    "test_plan": {
        "target": "目标接口",
        "strategies": ["FUNCTIONAL", "PARAMETER"],
        "focus": ["正常路径", "参数校验"],
        "estimated_points": 3,
    },
    "test_points": {
        "points": [
            {
                "name": "正常创建资源",
                "description": "合法参数应成功创建",
                "priority": "P0",
                "target_type": "API",
                "strategy_id": None,
                "api_id": None,
                "business_flow_id": None,
                "business_action_id": None,
                "rationale": "覆盖正常路径",
            },
            {
                "name": "缺少必填字段返回 400",
                "description": "缺必填参数应被拒绝",
                "priority": "P1",
                "target_type": "API",
                "strategy_id": None,
                "api_id": None,
                "business_flow_id": None,
                "business_action_id": None,
                "rationale": "覆盖参数校验",
            },
        ]
    },
    "test_cases": {
        "cases": [
            {
                "name": "正常创建资源-用例",
                "description": "合法参数创建成功并断言 200",
                "priority": "P0",
                "case_type": "FUNCTIONAL",
                "target_type": "API",
                "test_point_id": None,
                "api_id": None,
                "business_flow_id": None,
                "business_action_id": None,
                "preconditions": [],
                "test_data": [],
                "steps": [],
                "assertions": [
                    {"assertion_type": "STATUS_CODE", "source": None, "path": None,
                     "operator": "EQ", "expected_value": "200", "required": True,
                     "step_id": None, "sort": 0}
                ],
                "rationale": "覆盖正常路径",
            }
        ]
    },
    "result_analysis": {
        "summary": "执行完成，1 条用例失败",
        "issues": [
            {"severity": "ASSERTION_FAILURE", "case_id": None,
             "summary": "状态码断言未通过", "detail": "期望 200，实际 500"}
        ],
        "recommendation": "建议人工复核失败用例的测试数据与接口实现",
    },
    # Phase 2：报告 AI 总结默认样例（reports.services.ai_summary 校验通过的结构）。
    "report_summary": {
        "overview": "本次执行 1 条用例失败，通过率 0%，风险等级 HIGH。",
        "key_findings": ["P0 用例状态码断言未通过"],
        "potential_issues": [],
        "test_data_issues": [],
        "environment_issues": [],
        "recommendations": ["建议复核失败用例对应接口实现"],
        "risk_summary": "HIGH：存在 P0 用例失败，需优先处理。",
    },
    # Phase 2：Web 智能体决策默认样例（decision=OBSERVE 表示继续观察）。
    "web_decide": {
        "decision": "OBSERVE",
        "step": None,
        "rationale": "继续观察页面，等待下一步决策。",
    },
    "default": {"result": "ok"},
}
