// generationReview.mjs 的类型声明。

export interface DraftLike {
  status: string;
  module: string;
}

export interface ModuleErrorLike {
  status?: string;
}

export interface ReviewBody {
  action: 'accept' | 'reject';
  scope: 'all' | 'module';
  module?: string;
  comment?: string;
  confirm: boolean;
}

export interface QualitySummary {
  error: number;
  warning: number;
  info: number;
}

export interface MetricLike {
  module?: string;
  status?: string;
  duration_ms?: number | null;
  usage?: Record<string, number>;
}

export function pendingCount(drafts: DraftLike[] | null | undefined): number;
export function pendingModules(drafts: DraftLike[] | null | undefined): string[];
export function hasFailedModule(moduleErrors: ModuleErrorLike[] | null | undefined): boolean;
export function buildReviewBody(input: { action: 'accept' | 'reject'; scope: 'all' | 'module'; module?: string; comment?: string }): ReviewBody;
export function summarizeQuality(quality: { level: string }[] | null | undefined): QualitySummary;
export function formatMetric(item: MetricLike): string;
