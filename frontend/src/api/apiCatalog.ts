// 接口管理相关接口。字段命名与后端 api_catalog schemas 严格对齐（snake_case）。
// 权限：读 = 项目可见（viewer+）；写（建/改/删/移动/参数/响应/关联/导入）= 项目 member+；
// 调试 = 平台管理员（require_platform_admin）。越权按 404 返回，前端不展示。
//
// 路由形态：单 APIRouter 挂在 /api/v1 下，资源级路径（无额外前缀）：
//   /projects/{project_id}/api-modules、/api-modules/{module_id}
//   /projects/{project_id}/apis、/apis/{api_id}(/request|/responses|/relations|/history|/move|/debug)
//   /api-relations/{relation_id}
//   /projects/{project_id}/apis/import/(preview|confirm)、/projects/{project_id}/api-import-records
import { api } from './client';
import type {
  ApiBodyIn,
  ApiChangeLog,
  ApiDebugRequest,
  ApiDebugResult,
  ApiImportConfirmRequest,
  ApiImportConfirmResponse,
  ApiImportPreviewRequest,
  ApiImportPreviewResponse,
  ApiImportRecord,
  ApiInterface,
  ApiInterfaceCreate,
  ApiListQuery,
  ApiInterfaceDetail,
  ApiInterfaceMove,
  ApiInterfaceUpdate,
  ApiItemListResponse,
  ApiModule,
  ApiModuleCreate,
  ApiModuleMove,
  ApiModuleUpdate,
  ApiParameterIn,
  ApiRelation,
  ApiRelationCreate,
  ApiRequestBundle,
  ApiRequestBundleResponse,
  ApiResponsesBundle,
  ApiResponsesBundleResponse,
  ApiResponseIn,
  Paginated,
} from '@/types';

/**
 * 接口管理接口集合，由接口管理页调用。
 * 端点覆盖：模块 CRUD、接口 CRUD/移动、请求参数/响应整体替换、关联、变更记录、导入预览/确认/记录、调试。
 */
export const apiCatalogApi = {
  // ---- 模块 ----
  /** 模块树（含未分类默认模块），返回数组（非分页）。 */
  listModules: (projectId: number) =>
    api.get<ApiModule[]>(`/projects/${projectId}/api-modules`),
  /** 新建模块（≤2级，service 校验层级与重名）。 */
  createModule: (projectId: number, body: ApiModuleCreate) =>
    api.post<ApiModule>(`/projects/${projectId}/api-modules`, body),
  /** 编辑模块（未分类不可改名）。 */
  updateModule: (moduleId: number, body: ApiModuleUpdate) =>
    api.patch<ApiModule>(`/api-modules/${moduleId}`, body),
  /** 移动模块（改 parent_id，校验两级与无环）。 */
  moveModule: (moduleId: number, body: ApiModuleMove) =>
    api.patch<ApiModule>(`/api-modules/${moduleId}/move`, body),
  /** 删除模块（未分类不可删；子接口归未分类）。 */
  removeModule: (moduleId: number) =>
    api.delete<void>(`/api-modules/${moduleId}`),

  // ---- 接口 ----
  /** 接口列表，支持 keyword/method/module_id/status 过滤。 */
  listApis: (projectId: number, params: ApiListQuery) =>
    api.get<Paginated<ApiInterface>>(`/projects/${projectId}/apis`, { params }),
  /** 手工创建接口（source_type=MANUAL）。 */
  createApi: (projectId: number, body: ApiInterfaceCreate) =>
    api.post<ApiInterfaceDetail>(`/projects/${projectId}/apis`, body),
  /** 接口详情（含 module/参数/响应概要）。 */
  getApi: (apiId: number) => api.get<ApiInterfaceDetail>(`/apis/${apiId}`),
  /** 编辑接口基本信息。 */
  updateApi: (apiId: number, body: ApiInterfaceUpdate) =>
    api.patch<ApiInterfaceDetail>(`/apis/${apiId}`, body),
  /** 删除接口（级联子表）。 */
  removeApi: (apiId: number) => api.delete<void>(`/apis/${apiId}`),
  /** 移动接口到指定模块。 */
  moveApi: (apiId: number, body: ApiInterfaceMove) =>
    api.patch<ApiInterfaceDetail>(`/apis/${apiId}/move`, body),

  // ---- 请求参数 / body ----
  /** 请求参数+body。 */
  getRequest: (apiId: number) =>
    api.get<ApiRequestBundleResponse>(`/apis/${apiId}/request`),
  /** 整体替换参数+body。 */
  saveRequest: (apiId: number, body: ApiRequestBundle) =>
    api.put<ApiRequestBundleResponse>(`/apis/${apiId}/request`, body),

  // ---- 响应 ----
  /** 响应列表（按 status_code）。 */
  getResponses: (apiId: number) =>
    api.get<ApiResponsesBundleResponse>(`/apis/${apiId}/responses`),
  /** 整体替换响应。 */
  saveResponses: (apiId: number, body: ApiResponsesBundle) =>
    api.put<ApiResponsesBundleResponse>(`/apis/${apiId}/responses`, body),

  // ---- 关联 ----
  /** 关联列表。 */
  listRelations: (apiId: number) =>
    api.get<ApiItemListResponse<ApiRelation>>(`/apis/${apiId}/relations`),
  /** 新增关联（source/target 必须同项目）。 */
  createRelation: (apiId: number, body: ApiRelationCreate) =>
    api.post<ApiRelation>(`/apis/${apiId}/relations`, body),
  /** 删除关联。 */
  removeRelation: (relationId: number) =>
    api.delete<void>(`/api-relations/${relationId}`),

  // ---- 变更记录 ----
  /** 接口变更记录（分页）。 */
  listHistory: (apiId: number, params: { page?: number; page_size?: number }) =>
    api.get<ApiItemListResponse<ApiChangeLog>>(`/apis/${apiId}/history`, {
      params,
    }),

  // ---- 导入 ----
  /** 导入预览：自动识别 cURL/OpenAPI/Swagger/Postman 后分类，不入库。 */
  importPreview: (projectId: number, body: ApiImportPreviewRequest) =>
    api.post<ApiImportPreviewResponse>(
      `/projects/${projectId}/apis/import/preview`,
      body,
    ),
  /** 导入确认：重新解析+去重+入库（幂等），写 import_record + change_log。 */
  importConfirm: (projectId: number, body: ApiImportConfirmRequest) =>
    api.post<ApiImportConfirmResponse>(
      `/projects/${projectId}/apis/import/confirm`,
      body,
    ),
  /** 导入记录列表。 */
  listImportRecords: (
    projectId: number,
    params: { page?: number; page_size?: number },
  ) =>
    api.get<ApiItemListResponse<ApiImportRecord>>(
      `/projects/${projectId}/api-import-records`,
      { params },
    ),

  // ---- 调试（仅平台管理员） ----
  /** 发送真实请求（强制校验项目出站白名单）。 */
  debug: (apiId: number, body: ApiDebugRequest) =>
    api.post<ApiDebugResult>(`/apis/${apiId}/debug`, body),
};

// 写入载荷的类型再导出一份，供页面组件 Form 直接引用（避免重复定义）。
export type {
  ApiParameterIn,
  ApiBodyIn,
  ApiResponseIn,
  ApiRequestBundle,
  ApiResponsesBundle,
  ApiRelationCreate,
  ApiInterfaceCreate,
  ApiInterfaceUpdate,
  ApiModuleCreate,
  ApiModuleUpdate,
  ApiModuleMove,
  ApiInterfaceMove,
  ApiImportPreviewRequest,
  ApiImportConfirmRequest,
  ApiDebugRequest,
};
