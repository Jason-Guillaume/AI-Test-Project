"""验收项 24：Security Testing Phase D——重放循环与业务计划项生成。

覆盖开发计划 §6.4（重放 / 重复提交 / 业务状态 / 跳步）、§12（业务集成）、§16.3
（预览计划项形状）与 §18.4（高风险确认）。全部是纯函数测试：不连数据库、不发 HTTP、
不启动 FastAPI，重放循环用一个假的 execute 回调。

关键锁点：
- 重放次数只允许 2 或 3，间隔只允许 0～5000；越界直接报错，不静默改次数
- 回调被调用 2 次而不是 N 次；间隔只发生在两次执行之间，最后一次之后不再等待
- DUPLICATE_SUBMIT 只挂到创建 / 提交 / 支付类动作，或幂等规则点名的动作
- 终态计划缺 Fixture 时 ``blocked_reason=SECURITY_FIXTURE_REQUIRED``，计划项仍保留
- 跳步计划的 target 是后置 Action，而不是整条 Flow；不给 ``execute_flow`` 加 skip 参数
"""

from __future__ import annotations

import ast
from types import SimpleNamespace

import pytest

from app.features.security_testing.runtime.assertion import assert_expectation
from app.features.security_testing.runtime.business_plan import (
    FIXTURE_REQUIRED,
    business_state_item,
    default_state_fixture_key,
    duplicate_submit_item,
    fixture_gap,
    is_duplicate_candidate,
    item_name,
    needs_confirmation,
    next_action,
    replay_item,
    sequence_bypass_item,
)
from app.features.security_testing.runtime.replay import (
    MAX_REPLAY_INTERVAL_MS,
    read_replay_params,
    run_replay,
)
from app.core.http.errors import CODE_SECURITY_MUTATION_INVALID, AppError
from tests.conftest import BACKEND_DIR

EXECUTOR_PATH = BACKEND_DIR / "app" / "features" / "business" / "executors" / "business_flow_executor.py"


# --------------------------------------------------------------------------- 构造助手


def _rule(**overrides) -> dict:
    """一条重放类规则（dict 形态，business_plan 两种都能读）。"""
    base = dict(
        id=11,
        mutation_type="REPLAY_SAME_REQUEST",
        mutation_config={},
        expected_security_behavior="EXPECTED_IDEMPOTENT",
        expected_status_codes=None,
        severity="MEDIUM",
        confirmation_required=False,
    )
    base.update(overrides)
    return base


def _action(action_id: int = 2, action_key: str = "ASSIGN_TASK", sort: int = 2,
            name: str = "分配执行人") -> dict:
    """构造业务动作测试数据。"""
    return {"id": action_id, "action_key": action_key, "sort": sort, "name": name}


def _flow_actions() -> list[dict]:
    """构造业务流程的动作列表。"""
    return [
        {"id": 1, "action_key": "CREATE_TASK", "sort": 1, "name": "创建任务"},
        {"id": 2, "action_key": "ASSIGN_TASK", "sort": 2, "name": "分配执行人"},
        {"id": 3, "action_key": "RUN_TASK", "sort": 3, "name": "执行任务"},
        {"id": 4, "action_key": "COMPLETE_TASK", "sort": 4, "name": "完成任务"},
    ]


class FakeExecutor:
    """记录调用次数的假执行器：不连网，只按预设返回结果。"""

    def __init__(self, statuses=(200, 200), bodies=(), errors=()):
        """初始化对象状态。"""
        self.statuses = list(statuses)
        self.bodies = list(bodies)
        self.errors = list(errors)
        self.calls = 0

    def __call__(self, request):
        """执行对象封装的调用逻辑。"""
        index = min(self.calls, len(self.statuses) - 1)
        self.calls += 1
        return SimpleNamespace(
            status_code=self.statuses[index],
            response_body=self.bodies[index] if index < len(self.bodies) else None,
            response_headers={},
            response_time_ms=1,
            request_url="",
            error_message=self.errors[index] if index < len(self.errors) else None,
        )


def _expect_error(exc_type, code: str, fn):
    """断言抛出的异常类型与错误码，返回异常实例。"""
    with pytest.raises(exc_type) as caught:
        fn()
    assert caught.value.code == code, caught.value.code
    return caught.value


# --------------------------------------------------------------------------- 重放循环


class TestReplayLoop:
    """§6.4：次数受限的重复执行。"""

    def test_calls_execute_exactly_twice(self) -> None:
        """验收：回调被调用 2 次而不是 N 次。"""
        marker = object()
        executor = FakeExecutor(statuses=(200, 409))
        outcome = run_replay(marker, executor)
        assert executor.calls == 2
        assert outcome.attempts == 2
        assert outcome.statuses == (200, 409)

    def test_three_calls_are_allowed(self) -> None:
        """验证`three``calls`是否为`allowed`场景及其预期结果。"""
        executor = FakeExecutor(statuses=(200, 200, 200))
        outcome = run_replay(object(), executor, count=3)
        assert executor.calls == 3
        assert outcome.statuses == (200, 200, 200)

    @pytest.mark.parametrize("count", [0, 1, 4, 5, 10])
    def test_count_outside_2_or_3_is_rejected(self, count: int) -> None:
        """上限是 3：4 次不会被「看起来像 3 次」地执行掉。"""
        _expect_error(AppError, CODE_SECURITY_MUTATION_INVALID,
                      lambda: run_replay(object(), FakeExecutor(), count=count))

    @pytest.mark.parametrize("interval_ms", [-1, MAX_REPLAY_INTERVAL_MS + 1, 60000])
    def test_interval_outside_cap_is_rejected(self, interval_ms: int) -> None:
        """验证`interval``outside``cap`是否被拒绝场景及其预期结果。"""
        _expect_error(AppError, CODE_SECURITY_MUTATION_INVALID,
                      lambda: run_replay(object(), FakeExecutor(), interval_ms=interval_ms))

    def test_interval_is_applied_between_attempts_only(self) -> None:
        """间隔只发生在两次执行之间，最后一次之后不再等待。"""
        sleeps: list[float] = []
        executor = FakeExecutor(statuses=(200, 409))
        run_replay(object(), executor, count=2, interval_ms=250, sleep=sleeps.append)
        assert sleeps == [0.25]

    def test_zero_interval_never_sleeps(self) -> None:
        """验证`zero``interval``never``sleeps`场景及其预期结果。"""
        sleeps: list[float] = []
        run_replay(object(), FakeExecutor(), count=3, interval_ms=0, sleep=sleeps.append)
        assert sleeps == []

    def test_execute_receives_the_same_request(self) -> None:
        """循环不改请求，每次拿到的都是同一个对象。"""
        marker = object()
        seen: list = []

        def execute(request):
            """执行对应数据。"""
            seen.append(request)
            return SimpleNamespace(status_code=200, response_body="", error_message=None)

        run_replay(marker, execute, count=3)
        assert seen == [marker, marker, marker]

    def test_transport_error_is_recorded_not_swallowed(self) -> None:
        """验证`transport`错误是否`recorded`不`swallowed`场景及其预期结果。"""
        executor = FakeExecutor(statuses=(0, 200), errors=("连接超时", None))
        outcome = run_replay(object(), executor)
        assert outcome.errors == ("连接超时", None)
        assert outcome.error_messages == ["连接超时"]

    def test_executor_exception_propagates(self) -> None:
        """执行器抛异常时向上传递，由调用方按 FAILED_EXECUTION 处理。"""

        def execute(request):
            """执行对应数据。"""
            raise TimeoutError("连接超时")

        with pytest.raises(TimeoutError):
            run_replay(object(), execute)

    def test_outcome_feeds_the_idempotent_assertion(self) -> None:
        """重放结果直接交给断言层做幂等判定。"""
        executor = FakeExecutor(statuses=(200, 409), bodies=({"id": 1}, {"message": "重复"}))
        outcome = run_replay(object(), executor)
        result = assert_expectation(
            "EXPECTED_IDEMPOTENT", list(outcome.statuses),
            response_bodies=list(outcome.bodies), rule_name="重复提交",
        )
        assert result.security_result == "PASS"


class TestReplayParams:
    """规则配置里的次数与间隔：默认值、容错、越界。"""

    def test_defaults(self) -> None:
        """验证`defaults`场景及其预期结果。"""
        assert read_replay_params(None) == (2, 0)
        assert read_replay_params({}) == (2, 0)

    def test_reads_explicit_values(self) -> None:
        """验证`reads``explicit``values`场景及其预期结果。"""
        assert read_replay_params({"replay_count": 3, "replay_interval_ms": 1200}) == (3, 1200)

    def test_tolerates_string_and_float(self) -> None:
        """验证`tolerates``string`和`float`场景及其预期结果。"""
        assert read_replay_params({"replay_count": "3", "replay_interval_ms": 1000.0}) == (3, 1000)

    def test_boolean_is_not_a_count(self) -> None:
        """布尔值会被 JSON 当成 1/0，不能当成次数：报错而不是退回默认值。"""
        _expect_error(AppError, CODE_SECURITY_MUTATION_INVALID,
                      lambda: read_replay_params({"replay_count": True}))

    @pytest.mark.parametrize("count", [1, 4, 100, "x", [2]])
    def test_bad_count_is_rejected(self, count) -> None:
        """验证`bad`统计是否被拒绝场景及其预期结果。"""
        _expect_error(AppError, CODE_SECURITY_MUTATION_INVALID,
                      lambda: read_replay_params({"replay_count": count}))

    @pytest.mark.parametrize("interval_ms", [-1, 5001, 60000, "abc"])
    def test_bad_interval_is_rejected(self, interval_ms) -> None:
        """验证`bad``interval`是否被拒绝场景及其预期结果。"""
        _expect_error(AppError, CODE_SECURITY_MUTATION_INVALID,
                      lambda: read_replay_params({"replay_interval_ms": interval_ms}))


# --------------------------------------------------------------------------- 高风险确认


class TestNeedsConfirmation:
    """§18.4：这些规则生成时 confirmation_required=true。"""

    @pytest.mark.parametrize("method", ["DELETE", "delete"])
    def test_method_mutation_to_delete(self, method: str) -> None:
        """验证方法变异到删除场景及其预期结果。"""
        assert needs_confirmation(mutation_type="METHOD_MUTATION", method=method) is True

    @pytest.mark.parametrize("method", ["GET", "POST", "PUT"])
    def test_method_mutation_to_non_delete_does_not(self, method: str) -> None:
        """验证方法变异到`non`删除是否不场景及其预期结果。"""
        assert needs_confirmation(mutation_type="METHOD_MUTATION", method=method) is False

    @pytest.mark.parametrize("mutation_type,method", [
        ("REPLAY_SAME_REQUEST", "GET"),
        ("REPLAY_SAME_REQUEST", "POST"),
        ("DUPLICATE_SUBMIT", "POST"),
    ])
    def test_replay_and_duplicate_always_need_confirmation(self, mutation_type: str, method: str) -> None:
        """重放与重复提交无论方法都要求确认。"""
        assert needs_confirmation(mutation_type=mutation_type, method=method) is True

    @pytest.mark.parametrize("mutation_type", ["BUSINESS_STATE", "SEQUENCE_BYPASS"])
    @pytest.mark.parametrize("method,expected", [
        ("POST", True), ("PUT", True), ("PATCH", True), ("DELETE", True),
        ("GET", False), ("get", False), (None, True),
    ])
    def test_business_state_only_for_write_methods(self, mutation_type: str, method, expected: bool) -> None:
        """目标方法不是 GET 才要求确认；方法缺失按写操作处理。"""
        assert needs_confirmation(mutation_type=mutation_type, method=method) is expected

    @pytest.mark.parametrize("risk,method,expected", [
        ("HIGH", "POST", True),
        ("CRITICAL", "PATCH", True),
        ("HIGH", "GET", False),
        ("MEDIUM", "POST", False),
        ("LOW", "POST", False),
        ("INFO", "POST", False),
    ])
    def test_strategy_risk_level(self, risk: str, method: str, expected: bool) -> None:
        """验证策略风险`level`场景及其预期结果。"""
        assert needs_confirmation(mutation_type="REMOVE_TOKEN", method=method,
                                  strategy_risk_level=risk) is expected

    def test_rule_flag_always_wins(self) -> None:
        """验证规则`flag``always``wins`场景及其预期结果。"""
        assert needs_confirmation(mutation_type="REMOVE_TOKEN", method="GET",
                                  confirmation_required=True) is True


class TestDuplicateCandidate:
    """DUPLICATE_SUBMIT 只挂到创建/提交/支付类动作，或幂等规则点名的动作。"""

    @pytest.mark.parametrize("key", [
        "CREATE_TASK", "SUBMIT_ORDER", "PAY_ORDER", "SAVE_DRAFT", "ADD_USER", "INSERT_RECORD",
    ])
    def test_write_like_action_keys(self, key: str) -> None:
        """验证写入`like`动作`keys`场景及其预期结果。"""
        assert is_duplicate_candidate(key) is True

    @pytest.mark.parametrize("key", [
        "LOGIN", "GET_TASK", "RUN_TASK", "DELETE_TASK", "UPDATE_TASK", "QUERY_LIST", "",
    ])
    def test_non_write_action_keys(self, key: str) -> None:
        """验证`non`写入动作`keys`场景及其预期结果。"""
        assert is_duplicate_candidate(key) is False

    def test_idempotency_rule_type_counts(self) -> None:
        """验证`idempotency`规则类型`counts`场景及其预期结果。"""
        assert is_duplicate_candidate("RUN_TASK", ["IDEMPOTENCY"]) is True
        assert is_duplicate_candidate("RUN_TASK", ["idempotency"]) is True

    def test_rule_expression_is_not_evaluated(self) -> None:
        """business_rule.expression 不解析、不参与判定。"""
        assert is_duplicate_candidate("RUN_TASK", ["IDEMPOTENCY + amount > 0"]) is False
        assert is_duplicate_candidate("RUN_TASK", ["amount > 0"]) is False


class TestFixtureGap:
    """计划项点名了 Fixture 但作用域里拿不到时标记 blocked。"""

    def test_unknown_scope_does_not_block(self) -> None:
        """预览阶段还不知道有哪些 Fixture，不阻断。"""
        config = {"token_source": {"fixture_key": "USER_B", "output": "token"}}
        assert fixture_gap(config, None) is None

    def test_missing_fixture_blocks(self) -> None:
        """验证缺失固定数据`blocks`场景及其预期结果。"""
        config = {"resource_source": {"fixture_key": "TASK_B", "output": "task_id"}}
        assert fixture_gap(config, frozenset()) == FIXTURE_REQUIRED

    def test_available_fixture_does_not_block(self) -> None:
        """验证`available`固定数据是否不`block`场景及其预期结果。"""
        config = {"resource_source": {"fixture_key": "task_b", "output": "task_id"}}
        assert fixture_gap(config, {"TASK_B"}) is None

    def test_candidates_and_fixture_key_are_all_checked(self) -> None:
        """验证`candidates`和固定数据键是否为`all``checked`场景及其预期结果。"""
        config = {
            "candidates": [{"fixture_key": "USER_B", "output": "token"}],
            "fixture_key": "SUCCESS_TASK",
        }
        assert fixture_gap(config, {"USER_B"}) == FIXTURE_REQUIRED
        assert fixture_gap(config, {"USER_B", "SUCCESS_TASK"}) is None

    def test_config_without_sources_never_blocks(self) -> None:
        """验证配置不带`sources``never``blocks`场景及其预期结果。"""
        assert fixture_gap({}, frozenset()) is None
        assert fixture_gap(None, frozenset()) is None


# --------------------------------------------------------------------------- 业务计划项


class TestStateFixtureKey:
    """终态 Fixture 默认键：{POST_STATE}_{ENTITY}。"""

    def test_default_key(self) -> None:
        """验证默认键场景及其预期结果。"""
        assert default_state_fixture_key({"entity": "task", "post_state": "success"}) == "SUCCESS_TASK"

    def test_empty_parts_yield_empty_key(self) -> None:
        """验证空值`parts``yield`空值键场景及其预期结果。"""
        assert default_state_fixture_key({"entity": "task", "post_state": ""}) == ""
        assert default_state_fixture_key({"entity": "", "post_state": "success"}) == ""
        assert default_state_fixture_key({}) == ""


class TestNextAction:
    """跳步的目标：被跳过步骤之后的第一个动作。"""

    def test_next_is_the_action_after_the_skipped_one(self) -> None:
        """验证`next`是否`the`动作之后`the`跳过`one`场景及其预期结果。"""
        actions = _flow_actions()
        assert next_action(actions[1], actions)["id"] == 3

    def test_last_action_has_no_next(self) -> None:
        """验证`last`动作是否包含无`next`场景及其预期结果。"""
        assert next_action(_flow_actions()[-1], _flow_actions()) is None

    def test_empty_flow_has_no_next(self) -> None:
        """验证空值流程是否包含无`next`场景及其预期结果。"""
        assert next_action(_action(sort=1), []) is None

    def test_missing_next_action_returns_none(self) -> None:
        """actions 为 None 时不猜，直接返回 None。"""
        assert next_action(_action(sort=1), None) is None


class TestBusinessStateItem:
    """§6.4 / §12：post_state 有值才生成「用终态 Fixture 再调用此动作」的计划。"""

    def test_generates_item_when_post_state_exists(self) -> None:
        """验证`generates`条目当`post`状态存在场景及其预期结果。"""
        item = business_state_item(
            rule=_rule(), action=_action(),
            state={"entity": "task", "post_state": "success"},
        )
        assert item is not None
        assert item["mutation_type"] == "BUSINESS_STATE"
        assert item["target_type"] == "BUSINESS_ACTION"
        assert item["business_action_id"] == 2
        assert item["mutation_config"]["fixture_key"] == "SUCCESS_TASK"
        assert item["mutation_config"]["state_entity"] == "TASK"

    def test_no_item_when_post_state_is_empty(self) -> None:
        """验证无条目当`post`状态是否空值场景及其预期结果。"""
        assert business_state_item(
            rule=_rule(), action=_action(), state={"entity": "task", "post_state": None},
        ) is None

    def test_blocked_when_terminal_fixture_is_missing(self) -> None:
        """验收：终态计划缺 Fixture 时 blocked_reason=SECURITY_FIXTURE_REQUIRED。"""
        item = business_state_item(
            rule=_rule(), action=_action(),
            state={"entity": "task", "post_state": "success"},
            available_fixtures=frozenset(),
        )
        assert item is not None          # 计划项保留，保存为禁用用例
        assert item["blocked_reason"] == FIXTURE_REQUIRED

    def test_not_blocked_when_fixture_is_available(self) -> None:
        """验证不被拦截当固定数据是否`available`场景及其预期结果。"""
        item = business_state_item(
            rule=_rule(), action=_action(),
            state={"entity": "task", "post_state": "success"},
            available_fixtures={"SUCCESS_TASK"},
        )
        assert item["blocked_reason"] is None

    def test_fixture_key_from_rule_config_wins(self) -> None:
        """验证固定数据键从规则配置`wins`场景及其预期结果。"""
        item = business_state_item(
            rule=_rule(mutation_config={"fixture_key": "DONE_ORDER"}),
            action=_action(), state={"entity": "order", "post_state": "done"},
        )
        assert item["mutation_config"]["fixture_key"] == "DONE_ORDER"

    def test_no_item_when_neither_entity_nor_fixture_key(self) -> None:
        """验证无条目当`neither``entity``nor`固定数据键场景及其预期结果。"""
        assert business_state_item(
            rule=_rule(), action=_action(), state={"entity": "", "post_state": "success"},
        ) is None

    def test_write_method_requires_confirmation(self) -> None:
        """验证写入方法需要`confirmation`场景及其预期结果。"""
        item = business_state_item(rule=_rule(), action=_action(), method="POST",
                                   state={"entity": "task", "post_state": "success"})
        assert item["confirmation_required"] is True
        item = business_state_item(rule=_rule(), action=_action(), method="GET",
                                   state={"entity": "task", "post_state": "success"})
        assert item["confirmation_required"] is False


class TestSequenceBypassItem:
    """验收：跳步计划的 target 是后置 Action，而不是一整条 Flow。"""

    def test_target_is_the_action_after_the_skipped_one(self) -> None:
        """验证目标是否`the`动作之后`the`跳过`one`场景及其预期结果。"""
        actions = _flow_actions()
        item = sequence_bypass_item(rule=_rule(), skipped_action=actions[0], actions=actions)
        assert item["mutation_type"] == "SEQUENCE_BYPASS"
        assert item["target_type"] == "BUSINESS_ACTION"
        assert item["business_action_id"] == 2          # 被跳过的步骤是 1
        assert item["name"].startswith("分配执行人-SEQUENCE_BYPASS")

    def test_skipped_action_is_never_the_target(self) -> None:
        """验证跳过动作是否`never``the`目标场景及其预期结果。"""
        actions = _flow_actions()
        skipped = actions[1]
        item = sequence_bypass_item(rule=_rule(), skipped_action=skipped, actions=actions)
        assert item["business_action_id"] != skipped["id"]
        assert item["mutation_config"]["skipped_action_id"] == skipped["id"]

    def test_no_target_when_skipped_is_the_last_action(self) -> None:
        """验证无目标当跳过是否`the``last`动作场景及其预期结果。"""
        actions = _flow_actions()
        assert sequence_bypass_item(
            rule=_rule(), skipped_action=actions[-1], actions=actions,
        ) is None

    def test_blocked_when_prerequisite_fixture_is_missing(self) -> None:
        """前置步骤缺 Fixture 时，计划项标记 blocked（执行时 SKIPPED）。"""
        actions = _flow_actions()
        item = sequence_bypass_item(
            rule=_rule(), skipped_action=actions[0], actions=actions,
            skipped_state={"entity": "task", "post_state": "success"},
            available_fixtures=frozenset(),
        )
        assert item["blocked_reason"] == FIXTURE_REQUIRED
        assert item["mutation_config"]["fixture_key"] == "SUCCESS_TASK"

    def test_not_blocked_when_fixture_is_available(self) -> None:
        """验证不被拦截当固定数据是否`available`场景及其预期结果。"""
        actions = _flow_actions()
        item = sequence_bypass_item(
            rule=_rule(), skipped_action=actions[0], actions=actions,
            skipped_state={"entity": "task", "post_state": "success"},
            available_fixtures={"SUCCESS_TASK"},
        )
        assert item["blocked_reason"] is None

    def test_rule_fixture_key_wins_over_derived_key(self) -> None:
        """验证规则固定数据键`wins``over``derived`键场景及其预期结果。"""
        actions = _flow_actions()
        item = sequence_bypass_item(
            rule=_rule(mutation_config={"fixture_key": "SEED_TASK"}),
            skipped_action=actions[0], actions=actions,
            skipped_state={"entity": "task", "post_state": "success"},
        )
        assert item["mutation_config"]["fixture_key"] == "SEED_TASK"


class TestDuplicateSubmitItem:
    """DUPLICATE_SUBMIT：只挂到创建/提交/支付类动作。"""

    def test_generate_for_create_like_action(self) -> None:
        """验证生成用于创建`like`动作场景及其预期结果。"""
        item = duplicate_submit_item(
            rule=_rule(mutation_type="DUPLICATE_SUBMIT"),
            action=_action(action_key="CREATE_TASK", name="创建任务"),
            method="POST",
        )
        assert item is not None
        assert item["mutation_type"] == "DUPLICATE_SUBMIT"
        assert item["target_type"] == "BUSINESS_ACTION"
        assert item["confirmation_required"] is True
        assert item["mutation_config"]["replay_count"] == 2

    def test_skip_non_write_action(self) -> None:
        """验证`skip``non`写入动作场景及其预期结果。"""
        assert duplicate_submit_item(
            rule=_rule(mutation_type="DUPLICATE_SUBMIT"),
            action=_action(action_key="RUN_TASK", name="执行任务"),
            method="POST",
        ) is None

    def test_out_of_range_replay_count_is_rejected_at_plan_time(self) -> None:
        """重复提交共用重放循环：越界次数在计划阶段就报错，不留到执行时。"""
        _expect_error(AppError, CODE_SECURITY_MUTATION_INVALID,
                      lambda: duplicate_submit_item(
                          rule=_rule(mutation_type="DUPLICATE_SUBMIT",
                                     mutation_config={"replay_count": 9}),
                          action=_action(action_key="CREATE_TASK"),
                          method="POST",
                      ))

    def test_accept_idempotency_rule(self) -> None:
        """验证`accept``idempotency`规则场景及其预期结果。"""
        item = duplicate_submit_item(
            rule=_rule(mutation_type="DUPLICATE_SUBMIT"),
            action=_action(action_key="RUN_TASK", name="执行任务"),
            method="POST", rule_types=["IDEMPOTENCY"],
        )
        assert item is not None
        assert item["business_action_id"] == 2


class TestReplayItem:
    """REPLAY_SAME_REQUEST 计划项：次数与间隔夹进允许范围后再快照。"""

    def test_defaults_are_snapped_into_the_item(self) -> None:
        """验证`defaults`是否为`snapped``into``the`条目场景及其预期结果。"""
        item = replay_item(rule=_rule(), target="创建任务", method="POST", api_id=5)
        assert item["mutation_type"] == "REPLAY_SAME_REQUEST"
        assert item["expectation"] == "EXPECTED_IDEMPOTENT"
        assert item["mutation_config"]["replay_count"] == 2
        assert item["mutation_config"]["replay_interval_ms"] == 0
        assert item["confirmation_required"] is True
        assert item["api_id"] == 5

    def test_explicit_count_and_interval_are_kept(self) -> None:
        """验证`explicit`统计和`interval`是否为`kept`场景及其预期结果。"""
        item = replay_item(
            rule=_rule(mutation_config={"replay_count": 3, "replay_interval_ms": 800}),
            target="创建任务",
        )
        assert item["mutation_config"]["replay_count"] == 3
        assert item["mutation_config"]["replay_interval_ms"] == 800

    def test_out_of_range_config_is_rejected_before_snapping(self) -> None:
        """验证`out``of``range`配置是否被拒绝之前`snapping`场景及其预期结果。"""
        _expect_error(AppError, CODE_SECURITY_MUTATION_INVALID,
                      lambda: replay_item(
                          rule=_rule(mutation_config={"replay_count": 9}), target="创建任务",
                      ))


class TestItemShape:
    """§16.3 的 preview item 形状。"""

    def test_item_has_the_preview_keys(self) -> None:
        """验证条目是否包含`the`预览`keys`场景及其预期结果。"""
        item = replay_item(rule=_rule(), target="创建任务", method="POST")
        for key in ("index", "name", "mutation_type", "target_type", "method", "expectation",
                    "expected_status_codes", "severity", "risk_level", "confirmation_required",
                    "blocked_reason", "mutation_config"):
            assert key in item, key
        assert item["index"] == 0
        assert item["blocked_reason"] is None
        assert item["severity"] == "MEDIUM"
        assert item["risk_level"] == "MEDIUM"

    def test_risk_level_comes_from_strategy(self) -> None:
        """验证风险`level``comes`从策略场景及其预期结果。"""
        item = replay_item(
            rule=_rule(severity="LOW"),
            target="创建任务",
            strategy={"id": 3, "risk_level": "HIGH"},
        )
        assert item["risk_level"] == "HIGH"
        assert item["severity"] == "LOW"
        assert item["source_strategy_id"] == 3
        assert item["source_rule_id"] == 11

    def test_item_name_shape(self) -> None:
        """验证条目名称`shape`场景及其预期结果。"""
        assert item_name("创建任务", "REMOVE_TOKEN", "Authorization") == "创建任务-REMOVE_TOKEN-Authorization"
        assert item_name(None, "REPLAY_SAME_REQUEST") == "目标-REPLAY_SAME_REQUEST"


# --------------------------------------------------------------------------- 边界


class TestFlowIsNotModified:
    """验收：不给 execute_flow 增加 skip 参数，跳步靠计划项指向后置 Action。"""

    def test_execute_flow_has_no_skip_parameter(self) -> None:
        """验证执行流程是否包含无`skip``parameter`场景及其预期结果。"""
        tree = ast.parse(EXECUTOR_PATH.read_text())
        fn = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "execute_flow"
        )
        params = [arg.arg for arg in fn.args.args + fn.args.kwonlyargs]
        assert params == ["db", "flow_id", "environment_id", "variables", "actor"], params
        assert not any("skip" in param for param in params)
