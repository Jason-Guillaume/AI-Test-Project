"""运行时上下文管理。

ExecutionContext 封装一次 Business Flow 执行中的运行时变量。
配置数据（BusinessFlow/BusinessAction 等）与运行数据（Context）分离。

结构：
{
  "variables": { "project_id": 1001, "task_id": 2001 },
  "actions": {
    "CREATE_PROJECT": { "project_id": 1001 },
    "CREATE_TASK": { "task_id": 2001 }
  }
}

variables：共享运行时变量（跨 Action 传递）
actions：每个 Action 的原始输出（调试/报告/Agent 分析用）

优先级：Runtime Context variables > Execution Request Variables > Environment Variables > 接口默认值
"""

from __future__ import annotations


class ExecutionContext:
    """运行时上下文：执行期间的变量存储。

    用法：
        ctx = ExecutionContext(variables={"username": "test01"})
        ctx.set("project_id", 1001)
        val = ctx.get("project_id")
        ctx.apply_ref("created_project_id", "project_id")  # VariableRef 执行
        ctx.set_action_output("CREATE_PROJECT", {"project_id": 1001})  # 保存 Action 原始输出
    """

    def __init__(self, variables: dict[str, object] | None = None):
        self._variables: dict[str, object] = dict(variables or {})
        self._action_outputs: dict[str, dict[str, object]] = {}

    @property
    def variables(self) -> dict[str, object]:
        """返回共享变量的只读副本。"""
        return dict(self._variables)

    @property
    def action_outputs(self) -> dict[str, dict[str, object]]:
        """返回所有 Action 输出的只读副本。"""
        return {k: dict(v) for k, v in self._action_outputs.items()}

    def set(self, key: str, value: object) -> None:
        """设置共享变量值。"""
        self._variables[key] = value

    def get(self, key: str, default: object = None) -> object:
        """获取共享变量值，不存在时返回 default。"""
        return self._variables.get(key, default)

    def has(self, key: str) -> bool:
        """判断共享变量是否存在。"""
        return key in self._variables

    def keys(self) -> list[str]:
        """返回所有共享变量名。"""
        return list(self._variables.keys())

    def apply_ref(self, source_key: str, target_key: str) -> bool:
        """将 source_key 的值传递到 target_key。

        用于 VariableRef 执行：source action 的 output 变量
        → target action 的 input 变量。

        Returns:
            True 如果 source_key 存在且传递成功；False 如果 source_key 不存在。
        """
        if source_key not in self._variables:
            return False
        self._variables[target_key] = self._variables[source_key]
        return True

    def set_action_output(self, action_key: str, output: dict[str, object]) -> None:
        """保存某个 Action 的原始输出（用于调试/报告/Agent 分析）。"""
        self._action_outputs[action_key] = dict(output)

    def get_action_output(self, action_key: str) -> dict[str, object] | None:
        """获取某个 Action 的原始输出。"""
        return self._action_outputs.get(action_key)

    def to_dict(self) -> dict[str, object]:
        """序列化为可存储的 dict（用于持久化到 context_json）。"""
        return {
            "variables": dict(self._variables),
            "actions": {k: dict(v) for k, v in self._action_outputs.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, object] | None) -> ExecutionContext:
        """从持久化的 dict 恢复上下文。

        兼容旧格式（平铺 dict）和新格式（{"variables": {...}, "actions": {...}}）。
        """
        if not data:
            return cls(variables={})

        # 新格式：{"variables": {...}, "actions": {...}}
        if "variables" in data and isinstance(data["variables"], dict):
            variables = dict(data["variables"])
            actions = {}
            if "actions" in data and isinstance(data["actions"], dict):
                for k, v in data["actions"].items():
                    if isinstance(v, dict):
                        actions[k] = dict(v)
            ctx = cls(variables=variables)
            ctx._action_outputs = actions
            return ctx

        # 旧格式：平铺 dict → 视为纯 variables
        return cls(variables=dict(data))
