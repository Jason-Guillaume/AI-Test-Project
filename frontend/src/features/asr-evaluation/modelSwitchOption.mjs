const SLOT_LABELS = {
  TEST: '待测模型', REFERENCE_A: '参考模型 A', REFERENCE_B: '参考模型 B',
};

/** Build a switch label from the frozen run and batch snapshots, preserving historical uncertainty. */
export function modelSwitchOption(run, jobSnapshot, statusLabel) {
  const request = run.request_snapshot ?? {};
  const connections = Array.isArray(jobSnapshot?.connections) ? jobSnapshot.connections : [];
  const connection = connections.find((item) => Number(item.id) === Number(run.connection_id));
  const slots = Array.isArray(jobSnapshot?.model_slots) ? jobSnapshot.model_slots : [];
  const frozenSlot = slots.find((item) => Number(item.legacy_connection_id) === Number(run.connection_id))?.slot;
  const slot = String(request.task_slot ?? frozenSlot ?? '');
  const role = SLOT_LABELS[slot]
    ?? (run.role === 'TEST' ? '待测模型' : '参考模型（具体槽位未记录）');
  const modelId = String(request.model_id ?? '');
  const connectionName = String(connection?.name ?? '');
  const modelName = connectionName && connectionName !== modelId
    ? `${connectionName} · ${modelId || '模型编号未报告'}`
    : modelId || connectionName || `连接 #${run.connection_id}`;
  const parameter = request.parameter_set && typeof request.parameter_set === 'object'
    ? String(request.parameter_set.name ?? '参数未命名') : '参数未报告';
  return {
    value: run.id,
    label: `${role} · ${modelName} · ${parameter} · ${statusLabel(run.status)}`,
  };
}
