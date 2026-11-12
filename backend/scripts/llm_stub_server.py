"""E2E 专用 OpenAI 兼容 LLM 桩服务器。

只供 scripts/e2e_case_generation.sh 启动；确定性响应，不访问外部模型服务、不消耗真实 Token。
识别规则：按 system 提示中的子 Agent 角色文案区分模块；Supervisor 审阅和旧 Agent 意图澄清单独识别。
失败注入：需求文本含 [stub-fail-<module>] 标记时，该模块对同一需求首次请求返回 500，
之后（含重新生成）正常成功——「部分失败 → 重新生成成功」可在一次 E2E 中确定性地完成。
日志只打印调用类别与结果，绝不打印提示词、响应正文或密钥。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# system 提示中的角色文案 → 生成模块。
_MODULE_MARKERS = {
    "接口用例设计子 Agent": "api",
    "Web UI用例设计子 Agent": "web",
    "安全用例设计子 Agent": "security",
    "ASR用例设计子 Agent": "asr",
    "AI 质量用例设计子 Agent": "ai",
}
_MODULE_LABEL = {"api": "接口", "web": "Web UI", "security": "安全", "asr": "ASR", "ai": "AI 质量"}

# (module, 需求哈希) → 已失败次数；只失败第一次。
_FAIL_ONCE: dict[tuple[str, str], int] = {}
_LOCK = threading.Lock()

_USAGE = {"prompt_tokens": 12, "completion_tokens": 34, "total_tokens": 46}


def _digest(text: str) -> str:
    """需求内容的稳定短哈希，用于失败记忆与用例标题区分。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def _review_payload() -> dict:
    """Supervisor 审阅结论（Review Schema）。"""
    return {"summary": "E2E 审阅：草稿覆盖了主路径与异常路径", "gaps": ["阈值与数据口径待人工确认"]}


def _cases_payload(module: str, user_content: str, count: int = 2) -> dict:
    """模块用例草稿（DesignResult Schema）；标题含需求哈希避免跨用例重名。"""
    label = _MODULE_LABEL[module]
    digest = _digest(user_content)
    cases = []
    for index in range(1, min(2, count) + 1):
        cases.append({
            "title": f"{label}用例-{digest}-{index}",
            "priority": "P1" if index == 1 else "P2",
            "requirement": f"验证{label}场景下的需求实现（E2E 桩生成 {index}）",
            "preconditions": ["前置条件已就绪"],
            "test_data": [f"合成数据-{index}"],
            "steps": [f"执行{label}操作步骤 1", f"执行{label}操作步骤 2"],
            "expected_results": ["返回明确定义的成功结果", "状态与数据符合预期"],
            "coverage": ["功能", "边界"],
            "needs_confirmation": [],
        })
    return {"cases": cases}


def _should_fail(module: str, user_content: str) -> bool:
    """需求含 [stub-fail-<module>] 标记时首次失败；此后放行。"""
    if f"[stub-fail-{module}]" not in user_content:
        return False
    key = (module, _digest(user_content))
    with _LOCK:
        if _FAIL_ONCE.get(key, 0) >= 1:
            return False
        _FAIL_ONCE[key] = 1
    return True


def _chat_response(payload: dict) -> dict:
    """OpenAI 兼容响应体。"""
    return {
        "id": "chatcmpl-e2e-stub",
        "object": "chat.completion",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": json.dumps(payload, ensure_ascii=False)},
            "finish_reason": "stop",
        }],
        "usage": dict(_USAGE),
    }


class _Handler(BaseHTTPRequestHandler):
    """只处理 POST /v1/chat/completions；其余路径 404。"""

    def do_POST(self) -> None:  # noqa: N802（http.server 约定）
        """按模块和请求数量返回可控合成响应。"""
        if self.path.rstrip("/") not in ("/v1/chat/completions", "/chat/completions"):
            self.send_error(404, "not found")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            messages = body.get("messages") or []
            system = next((str(item.get("content") or "") for item in messages if item.get("role") == "system"), "")
            user = "\n".join(str(item.get("content") or "") for item in messages if item.get("role") == "user")
            if "审阅模块子 Agent" in system:
                kind, payload = "review", _review_payload()
            elif "## 意图枚举" in system:
                kind, payload = "agent-intent", {
                    "intent": "CLARIFY", "target_ids": [],
                    "clarify_question": "请指定接口或业务流程目标。",
                }
            else:
                module = next((value for marker, value in _MODULE_MARKERS.items() if marker in system), None)
                if module is None:
                    kind, payload = "unknown", {"result": "ok"}
                elif _should_fail(module, user):
                    kind = f"{module}:fail-once"
                    self._reply(500, {"error": {"message": "e2e stub injected failure", "type": "stub_failure"}})
                    print(f"[llm-stub] {kind}", flush=True)
                    return
                else:
                    count = re.search(r'最多生成 (\d+) 条', system)
                    kind, payload = module, _cases_payload(module, user, int(count.group(1)) if count else 2)
            delay = re.search(r'\[stub-delay-(api|web|security|asr|ai)-(\d+)\]', user)
            if delay and kind == delay.group(1):
                time.sleep(min(10, int(delay.group(2))))
            self._reply(200, _chat_response(payload))
            print(f"[llm-stub] {kind} ok", flush=True)
        except Exception as exc:  # 桩本身出错也要返回结构化 500，避免悬挂后端请求。
            self._reply(500, {"error": {"message": f"stub error: {type(exc).__name__}", "type": "stub_error"}})
            print(f"[llm-stub] stub error: {type(exc).__name__}", flush=True)

    def _reply(self, status: int, payload: dict) -> None:
        """发送不含真实模型数据的 JSON 响应。"""
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:  # noqa: A002（父类签名）
        """静音默认访问日志；调用类别已由 do_POST 打印。"""


def main() -> None:
    """启动桩服务器。"""
    parser = argparse.ArgumentParser(description="E2E OpenAI 兼容 LLM 桩服务器")
    parser.add_argument("--port", type=int, default=8799)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), _Handler)
    print(f"[llm-stub] listening on 127.0.0.1:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
