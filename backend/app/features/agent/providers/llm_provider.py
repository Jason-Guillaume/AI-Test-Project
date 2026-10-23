"""LLM Provider：自写 httpx 调 OpenAI 兼容接口（§29/§30）。

- ProductionLLMProvider：从 ModelConfiguration 取 is_default+is_enabled 配置，
  decrypt_api_key 解密，httpx POST {api_base}/chat/completions。
  结构化输出用 response_format={"type":"json_object"}，解析后由节点做 Pydantic 校验。
- FakeLLMProvider：按 kind 返回固定结构化 JSON，测试用，不依赖网络/密钥。

密钥不入源码（§20/§29）：base_url/key 全部来自 ModelConfiguration，节点层不写。
无默认模型配置时友好报错 NO_DEFAULT_MODEL。
"""

from __future__ import annotations

import json
from typing import Any, Protocol

import httpx
from sqlalchemy.orm import Session

from app.features.agent.providers.langfuse_tracer import llm_generation, update_generation
from app.features.agent.providers.sanitizer import build_chat_messages
from app.features.model_configuration.services.model_config_service import decrypt_api_key
from app.models.configuration import ModelConfiguration


class LLMError(Exception):
    """LLM 调用失败。code 用于写入 state.error_code（§36）。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class LLMProvider(Protocol):
    """节点依赖的 LLM 接口（Protocol，便于测试注入 FakeLLMProvider）。"""

    def generate_structured(
        self, system: str, user_content: str, schema: dict[str, Any] | None = None,
        *, kind: str | None = None, history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """结构化产出：返回 JSON dict（由节点用 Pydantic 二次校验）。"""
        ...

    def chat(
        self, system: str, user_content: str,
        *, history: list[dict[str, str]] | None = None,
    ) -> str:
        """非结构化对话：返回文本。"""
        ...


class ProductionLLMProvider:
    """生产 LLM Provider：读 ModelConfiguration 默认配置，httpx 调 OpenAI 兼容。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def generate_structured(
        self, system: str, user_content: str, schema: dict[str, Any] | None = None,
        *, kind: str | None = None, history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        cfg = self._load_config()
        api_key = decrypt_api_key(cfg.api_key_encrypted)
        messages = build_chat_messages(system, user_content, history=history)
        body: dict[str, Any] = {
            "model": cfg.model_name,
            "messages": messages,
            "temperature": float(cfg.temperature or 0.2),
            "max_tokens": int(cfg.max_tokens or 4096),
            "response_format": {"type": "json_object"},
        }
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        url = f"{(cfg.api_base or '').rstrip('/')}/chat/completions"
        # Langfuse generation 埋点：关闭时为 no-op；LLMError 会被标记 ERROR 后原样抛出。
        with llm_generation(
            name=f"agent.generate_structured.{kind or 'unknown'}",
            model=cfg.model_name,
            input_messages=messages,
            model_parameters={"temperature": body["temperature"], "max_tokens": body["max_tokens"]},
        ) as gen:
            try:
                resp = httpx.post(url, json=body, headers=headers, timeout=float(cfg.timeout or 60))
            except httpx.HTTPError as exc:
                raise LLMError("LLM_FAILED", f"模型服务请求失败：{exc}") from exc
            if resp.status_code >= 400:
                raise LLMError("LLM_FAILED", f"模型服务返回 {resp.status_code}：{resp.text[:300]}")
            try:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError) as exc:
                raise LLMError("STRUCTURED_OUTPUT_INVALID", f"模型响应解析失败：{exc}") from exc
            update_generation(gen, output=content, usage=data.get("usage"))
            return self._parse_json_content(content)

    def chat(
        self, system: str, user_content: str,
        *, history: list[dict[str, str]] | None = None,
    ) -> str:
        cfg = self._load_config()
        api_key = decrypt_api_key(cfg.api_key_encrypted)
        messages = build_chat_messages(system, user_content, history=history)
        body = {
            "model": cfg.model_name,
            "messages": messages,
            "temperature": float(cfg.temperature or 0.2),
            "max_tokens": int(cfg.max_tokens or 4096),
        }
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        url = f"{(cfg.api_base or '').rstrip('/')}/chat/completions"
        # Langfuse generation 埋点：关闭时为 no-op；LLMError 会被标记 ERROR 后原样抛出。
        with llm_generation(
            name="agent.chat",
            model=cfg.model_name,
            input_messages=messages,
            model_parameters={"temperature": body["temperature"], "max_tokens": body["max_tokens"]},
        ) as gen:
            try:
                resp = httpx.post(url, json=body, headers=headers, timeout=float(cfg.timeout or 60))
            except httpx.HTTPError as exc:
                raise LLMError("LLM_FAILED", f"模型服务请求失败：{exc}") from exc
            if resp.status_code >= 400:
                raise LLMError("LLM_FAILED", f"模型服务返回 {resp.status_code}：{resp.text[:300]}")
            try:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError) as exc:
                raise LLMError("LLM_FAILED", f"模型响应解析失败：{exc}") from exc
            update_generation(gen, output=content, usage=data.get("usage"))
            return content

    def _load_config(self) -> ModelConfiguration:
        cfg = (
            self.db.query(ModelConfiguration)
            .filter(ModelConfiguration.is_default.is_(True), ModelConfiguration.is_enabled.is_(True))
            .first()
        )
        if cfg is None:
            raise LLMError("NO_DEFAULT_MODEL", "未配置启用的默认模型，无法调用 LLM")
        return cfg

    @staticmethod
    def _parse_json_content(content: str) -> dict[str, Any]:
        """模型可能返回带 ```json 围栏或多余文本，尽力抽取首个 JSON 对象。"""
        text = (content or "").strip()
        if not text:
            raise LLMError("STRUCTURED_OUTPUT_INVALID", "模型返回空内容")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # 退而抽取首个 {...} 片段。
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError as exc:
                raise LLMError("STRUCTURED_OUTPUT_INVALID", f"模型输出非合法 JSON：{exc}") from exc
        raise LLMError("STRUCTURED_OUTPUT_INVALID", "模型输出未包含 JSON 对象")


class FakeLLMProvider:
    """测试用桩：按 kind 返回固定结构化 JSON，绝不发起网络请求。

    通过 set_response(kind, payload) 注入期望产出；未设置时用内置默认样例。
    """

    def __init__(self) -> None:
        self._responses: dict[str, dict[str, Any]] = {}
        # 记录每次结构化调用的 (system, user_content, kind)，供测试断言敏感数据未泄入。
        self.calls: list[dict[str, Any]] = []

    def set_response(self, kind: str, payload: dict[str, Any]) -> None:
        self._responses[kind] = payload

    def generate_structured(
        self, system: str, user_content: str, schema: dict[str, Any] | None = None,
        *, kind: str | None = None, history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        self.calls.append({"system": system, "user": user_content, "kind": kind, "history": history or []})
        if kind and kind in self._responses:
            return self._responses[kind]
        return _DEFAULT_FAKE.get(kind or "default", {"result": "ok"})

    def chat(
        self, system: str, user_content: str,
        *, history: list[dict[str, str]] | None = None,
    ) -> str:
        self.calls.append({"system": system, "user": user_content, "kind": "chat", "history": history or []})
        return "（FakeLLM 回复）测试桩不产生真实内容。"

    @property
    def last_call(self) -> dict[str, Any] | None:
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
