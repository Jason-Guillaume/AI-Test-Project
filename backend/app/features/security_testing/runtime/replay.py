"""重放循环：把同一个变异请求按受限次数重复执行。

Phase 1 只做「次数受限的重复」：``replay_count`` 只接受 2 或 3，
``replay_interval_ms`` 默认 0、最大 5000。不做并发、不做无限重试，也不做任何
速率探测——``RATE_LIMIT`` 是预留攻击类，本阶段不执行。

执行函数由调用方注入（Phase E 的 runner 传 ``ApiRequestExecutor.execute`` 的包装），
本模块不 import httpx、不发请求，所以单测里可以直接传一个假的回调。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.core.http.errors import CODE_SECURITY_MUTATION_INVALID, AppError

__all__ = [
    "ReplayOutcome",
    "read_replay_params",
    "run_replay",
    "ALLOWED_REPLAY_COUNTS",
    "DEFAULT_REPLAY_COUNT",
    "DEFAULT_REPLAY_INTERVAL_MS",
    "MAX_REPLAY_INTERVAL_MS",
    "REPLAY_COUNT_KEY",
    "REPLAY_INTERVAL_KEY",
]

#: 次数与间隔的上限来自开发计划 §6.4；这里写死，不读配置。
MIN_REPLAY_COUNT = 2
MAX_REPLAY_COUNT = 3
ALLOWED_REPLAY_COUNTS: tuple[int, ...] = (MIN_REPLAY_COUNT, MAX_REPLAY_COUNT)
DEFAULT_REPLAY_COUNT = 2
DEFAULT_REPLAY_INTERVAL_MS = 0
MAX_REPLAY_INTERVAL_MS = 5000

REPLAY_COUNT_KEY = "replay_count"
REPLAY_INTERVAL_KEY = "replay_interval_ms"


@dataclass(frozen=True)
class ReplayOutcome:
    """一次重放循环的结果，按执行次序记录。

    ``statuses`` / ``bodies`` 顺序就是执行顺序，交给断言层做幂等比较。
    """

    statuses: tuple[int, ...]
    bodies: tuple[Any, ...]
    errors: tuple[str | None, ...]

    @property
    def attempts(self) -> int:
        """实际执行次数。"""
        return len(self.statuses)

    @property
    def error_messages(self) -> list[str]:
        """非空错误文案，空列表表示没有传输层错误。"""
        return [message for message in self.errors if message]


def _to_int(value: Any, *, key: str) -> int:
    """把配置里的次数或间隔读成整数。

    容忍 JSON 里写成字符串或 ``2.0`` 的情况；形状不对直接报错——静默退回默认值
    等于让一份坏配置按 2 次重放跑下去。
    """
    if isinstance(value, bool):
        raise AppError(f"{key} 必须是整数，实际 {value!r}", code=CODE_SECURITY_MUTATION_INVALID)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    text = str(value).strip() if isinstance(value, str) else ""
    if text.isdigit():
        return int(text)
    raise AppError(f"{key} 必须是整数，实际 {value!r}", code=CODE_SECURITY_MUTATION_INVALID)


def _validate_params(count: int, interval_ms: int) -> None:
    """次数与间隔越界直接报错：静默改次数等于改写了测试语义。"""
    if count not in ALLOWED_REPLAY_COUNTS:
        raise AppError(
            f"replay_count 只允许 {DEFAULT_REPLAY_COUNT} 或 {MAX_REPLAY_COUNT}，实际 {count}",
            code=CODE_SECURITY_MUTATION_INVALID,
        )
    if not 0 <= interval_ms <= MAX_REPLAY_INTERVAL_MS:
        raise AppError(
            f"replay_interval_ms 必须在 0 到 {MAX_REPLAY_INTERVAL_MS} 之间，实际 {interval_ms}",
            code=CODE_SECURITY_MUTATION_INVALID,
        )


def read_replay_params(mutation_config: Mapping[str, Any] | None) -> tuple[int, int]:
    """从规则配置读出 ``(次数, 间隔毫秒)``，缺省用默认值。

    Raises:
        AppError: 次数不是 2 或 3，或间隔超出 0～5000（``SECURITY_MUTATION_INVALID``）。
    """
    config = mutation_config or {}
    count = (
        _to_int(config[REPLAY_COUNT_KEY], key=REPLAY_COUNT_KEY)
        if REPLAY_COUNT_KEY in config
        else DEFAULT_REPLAY_COUNT
    )
    interval_ms = (
        _to_int(config[REPLAY_INTERVAL_KEY], key=REPLAY_INTERVAL_KEY)
        if REPLAY_INTERVAL_KEY in config
        else DEFAULT_REPLAY_INTERVAL_MS
    )
    _validate_params(count, interval_ms)
    return count, interval_ms


def _status_of(result: Any) -> int:
    """取一次执行的状态码；传输失败时保持 0。"""
    status = getattr(result, "status_code", 0)
    return int(status) if isinstance(status, int) else 0


def run_replay(
    request: Any,
    execute: Callable[[Any], Any],
    *,
    count: int = DEFAULT_REPLAY_COUNT,
    interval_ms: int = DEFAULT_REPLAY_INTERVAL_MS,
    sleep: Callable[[float], Any] = time.sleep,
) -> ReplayOutcome:
    """重复执行同一个请求 ``count`` 次，相邻两次之间按 ``interval_ms`` 等待。

    间隔只发生在两次执行之间：最后一次之后不再等待。每次执行拿到的都是同一个
    ``request`` 对象，循环本身不改它。``execute`` 抛出的异常直接向上传递，由调用方
    按 FAILED_EXECUTION 处理。

    Args:
        request: 已经变异的请求。
        execute: ``Callable[[request], 执行结果]``，结果需有 ``status_code``、
            ``response_body``、``error_message`` 三个属性。
        sleep: 注入的等待函数，测试里可以换成空实现。
    """
    _validate_params(count, interval_ms)
    statuses: list[int] = []
    bodies: list[Any] = []
    errors: list[str | None] = []
    for attempt in range(count):
        if attempt and interval_ms > 0:
            sleep(interval_ms / 1000)
        result = execute(request)
        statuses.append(_status_of(result))
        bodies.append(getattr(result, "response_body", None))
        errors.append(getattr(result, "error_message", None))
    return ReplayOutcome(tuple(statuses), tuple(bodies), tuple(errors))
