// 业务管理页常量：下拉选项与文案标签，与后端枚举字面量严格对齐。
// 仅放纯静态选项，不放业务逻辑。

import type {
  BusinessActionType,
  BusinessApiLocation,
  BusinessDomainStatus,
  BusinessFlowStatus,
  BusinessPreconditionOperator,
  BusinessPreconditionType,
  BusinessRuleType,
  BusinessVariableDataType,
} from '@/types';

export const DOMAIN_STATUS_OPTIONS = [
  { value: 'ACTIVE' as BusinessDomainStatus, label: '启用' },
  { value: 'INACTIVE' as BusinessDomainStatus, label: '停用' },
];

export const FLOW_STATUS_OPTIONS = [
  { value: 'DRAFT' as BusinessFlowStatus, label: '草稿' },
  { value: 'ACTIVE' as BusinessFlowStatus, label: '已上线' },
  { value: 'DEPRECATED' as BusinessFlowStatus, label: '已废弃' },
];

export const ACTION_TYPE_OPTIONS = [
  { value: 'NORMAL' as BusinessActionType, label: '常规动作' },
];

export const PRECONDITION_TYPE_OPTIONS = [
  { value: 'VARIABLE' as BusinessPreconditionType, label: '变量' },
  { value: 'STATE' as BusinessPreconditionType, label: '状态' },
  { value: 'BUSINESS' as BusinessPreconditionType, label: '业务' },
  { value: 'TEXT' as BusinessPreconditionType, label: '文本说明' },
];

export const PRECONDITION_OPERATOR_OPTIONS = [
  { value: 'EQ' as BusinessPreconditionOperator, label: '等于 (EQ)' },
  { value: 'NE' as BusinessPreconditionOperator, label: '不等于 (NE)' },
  { value: 'IN' as BusinessPreconditionOperator, label: '包含 (IN)' },
  { value: 'CONTAINS' as BusinessPreconditionOperator, label: '包含文本 (CONTAINS)' },
  { value: 'EXISTS' as BusinessPreconditionOperator, label: '存在 (EXISTS)' },
  { value: 'NOT_EXISTS' as BusinessPreconditionOperator, label: '不存在 (NOT_EXISTS)' },
];

export const VARIABLE_DIRECTION_OPTIONS = [
  { value: 'INPUT', label: '输入变量' },
  { value: 'OUTPUT', label: '输出变量' },
];

export const VARIABLE_DATA_TYPE_OPTIONS = [
  { value: 'STRING' as BusinessVariableDataType, label: '字符串 STRING' },
  { value: 'INTEGER' as BusinessVariableDataType, label: '整数 INTEGER' },
  { value: 'NUMBER' as BusinessVariableDataType, label: '数字 NUMBER' },
  { value: 'BOOLEAN' as BusinessVariableDataType, label: '布尔 BOOLEAN' },
  { value: 'OBJECT' as BusinessVariableDataType, label: '对象 OBJECT' },
  { value: 'ARRAY' as BusinessVariableDataType, label: '数组 ARRAY' },
];

// 输入映射位置：BODY/HEADER/QUERY/PATH；输出映射位置：RESPONSE（后端 service 校验）。
export const API_LOCATION_INPUT_OPTIONS: { value: BusinessApiLocation; label: string }[] = [
  { value: 'BODY', label: '请求体 BODY' },
  { value: 'HEADER', label: '请求头 HEADER' },
  { value: 'QUERY', label: '查询参数 QUERY' },
  { value: 'PATH', label: '路径参数 PATH' },
];

export const API_LOCATION_OUTPUT_OPTIONS: { value: BusinessApiLocation; label: string }[] = [
  { value: 'RESPONSE', label: '响应体 RESPONSE' },
];

export const RULE_TYPE_OPTIONS = [
  { value: 'GENERAL' as BusinessRuleType, label: '通用规则' },
  { value: 'CONSTRAINT' as BusinessRuleType, label: '约束规则' },
  { value: 'PRECONDITION' as BusinessRuleType, label: '前置规则' },
];
