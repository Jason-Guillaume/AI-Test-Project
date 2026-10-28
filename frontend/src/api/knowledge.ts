// 项目知识库 API：统一走 axios client，路由层不直接请求网络。
import { api } from './client';
import type { KnowledgeBase, KnowledgeCategory, KnowledgeChunk, KnowledgeDocument, KnowledgeDocumentVersion } from '@/types';

export const knowledgeApi = {
  listBases: (projectId: number) => api.get<KnowledgeBase[]>(`/projects/${projectId}/knowledge-bases`),
  createBase: (projectId: number) => api.post<KnowledgeBase>(`/projects/${projectId}/knowledge-bases`, {}),
  listDocuments: (baseId: number) => api.get<{ items: KnowledgeDocument[]; total: number }>(`/knowledge-bases/${baseId}/documents`),
  upload: (baseId: number, input: { title: string; category: KnowledgeCategory; file: File; document_id?: number }) => {
    const body = new FormData();
    body.append('title', input.title);
    body.append('category', input.category);
    if (input.document_id != null) body.append('document_id', String(input.document_id));
    body.append('file', input.file);
    return api.post<{ document: KnowledgeDocument; version: KnowledgeDocumentVersion; parse_job: { id: number; status: string } }>(
      `/knowledge-bases/${baseId}/documents`, body,
    );
  },
  versions: (documentId: number) => api.get<{ items: KnowledgeDocumentVersion[] }>(`/knowledge-documents/${documentId}/versions`),
  chunks: (versionId: number, page = 1) => api.get<{ items: KnowledgeChunk[]; total: number; page: number; page_size: number }>(
    `/knowledge-document-versions/${versionId}/chunks`, { params: { page, page_size: 100 } },
  ),
  setEnabled: (documentId: number, enabled: boolean) =>
    api.patch<KnowledgeDocument>(`/knowledge-documents/${documentId}/status`, { enabled }),
  retry: (versionId: number) => api.post<{ version_id: number; status: string }>(`/knowledge-document-versions/${versionId}/retry`, {}),
  remove: (documentId: number) => api.delete<void>(`/knowledge-documents/${documentId}`),
};
