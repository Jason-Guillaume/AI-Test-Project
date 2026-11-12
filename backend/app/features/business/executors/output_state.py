"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from app.features.business.models.business_variable_ref import BusinessVariableRef


def apply_output_refs(db, flow_id, action, ctx):
    """将动作输出通过既有 VariableRef 传递给后续动作，不改变上下文契约。"""
    refs = (
        db.query(BusinessVariableRef)
        .filter(BusinessVariableRef.flow_id == flow_id)
        .all()
    )
    for ref in refs:
        if ref.source_action_id == action.id and ref.target_action_id:
            # 模型列为 source_variable/target_variable（与 schemas 一致），此处必须同名读取。
            if ref.source_variable and ref.target_variable:
                # 优先从 action_output 命名空间查找，其次从 variables 查找。
                action_output = ctx.get_action_output(action.action_key)
                if action_output and ref.source_variable in action_output:
                    ctx.set(ref.target_variable, action_output[ref.source_variable])
                elif ref.source_variable in ctx.variables:
                    ctx.apply_ref(ref.source_variable, ref.target_variable)
