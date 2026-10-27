// 接口管理页共享常量：方法/状态/分类的颜色与下拉选项。
// 后端取值集合为准，这里只做展示映射，不自行扩值。
import type {
  ApiSourceType,
  ApiStatus,
  BodyType,
  ImportClassification,
  ParamLocation,
  RelationType,
} from '@/types';

// HTTP 方法色板：在模块树、列表、调试结果里给方法打 Tag。
export const METHOD_COLOR: Record<string, string> = {
  GET: 'green',
  POST: 'blue',
  PUT: 'cyan',
  PATCH: 'gold',
  DELETE: 'red',
  HEAD: 'default',
  OPTIONS: 'default',
};

// 接口生命周期状态色板。
export const API_STATUS_COLOR: Record<ApiStatus, string> = {
  ACTIVE: 'green',
  DRAFT: 'default',
  DEPRECATED: 'red',
  DEVELOPING: 'blue',
  MOCK: 'purple',
};

// 导入预览分类色板。
export const CLASSIFICATION_COLOR: Record<ImportClassification, string> = {
  NEW: 'green',
  EXISTING: 'default',
  CHANGED: 'orange',
  UNCHANGED: 'default',
};

export const CLASSIFICATION_LABEL: Record<ImportClassification, string> = {
  NEW: '新增',
  EXISTING: '已存在',
  CHANGED: '有变更',
  UNCHANGED: '无变化',
};

// 下拉选项（供 Select 用）。
export const METHOD_OPTIONS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'].map(
  (m) => ({ label: m, value: m }),
);

export const API_STATUS_OPTIONS: { label: string; value: ApiStatus }[] = [
  { label: '启用中', value: 'ACTIVE' },
  { label: '草稿', value: 'DRAFT' },
  { label: '已废弃', value: 'DEPRECATED' },
  { label: '开发中', value: 'DEVELOPING' },
  { label: 'Mock', value: 'MOCK' },
];

export const PARAM_LOCATION_OPTIONS: { label: string; value: ParamLocation }[] = [
  { label: 'PATH', value: 'PATH' },
  { label: 'QUERY', value: 'QUERY' },
  { label: 'HEADER', value: 'HEADER' },
  { label: 'COOKIE', value: 'COOKIE' },
];

export const BODY_TYPE_OPTIONS: { label: string; value: BodyType }[] = [
  { label: '无', value: 'none' },
  { label: 'JSON', value: 'json' },
  { label: 'Form', value: 'form' },
  { label: 'Multipart', value: 'multipart' },
  { label: 'Raw', value: 'raw' },
];

export const RELATION_TYPE_OPTIONS: { label: string; value: RelationType }[] = [
  { label: '前置条件', value: 'PRECONDITION' },
  { label: '输出→输入', value: 'OUTPUT_INPUT' },
  { label: '后续步骤', value: 'FOLLOW_UP' },
];

// 导入来源选项；文档类格式由后端自动识别，避免文件类型选错导致无法导入。
export const IMPORT_SOURCE_OPTIONS: { label: string; value: ApiSourceType }[] = [
  { label: 'Curl', value: 'CURL' },
  { label: 'OpenAPI / Swagger', value: 'OPENAPI' },
  { label: 'Postman Collection', value: 'POSTMAN' },
];
