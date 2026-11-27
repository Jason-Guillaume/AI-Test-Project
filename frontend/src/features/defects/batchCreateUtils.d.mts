// batchCreateUtils.mjs 的 TypeScript 类型声明。

import type {
  BugBatchCreateItem,
  BugBatchRowError,
  BugCategory,
  BugSeverity,
} from './contracts';

export const MAX_BATCH_BUG_ROWS: number;

export interface BatchDefectDefaults {
  category?: BugCategory;
  severity: BugSeverity;
  environment?: string;
}

export interface BatchDefectDraftRow {
  key: string;
  title: string;
  category?: BugCategory;
  severity: BugSeverity;
  description: string;
  steps_to_reproduce: string;
  environment: string;
  expected_result: string;
  actual_result: string;
}

export function normalizeCategoryToken(raw: unknown): BugCategory | undefined;
export function normalizeSeverityToken(raw: unknown): BugSeverity | undefined;
export function createDraftRow(defaults: BatchDefectDefaults, key: string): BatchDefectDraftRow;
export function isPristineEmptyRow(row: BatchDefectDraftRow | undefined): boolean;
export function parseBatchDefectLines(
  rawText: string,
  defaults: BatchDefectDefaults,
  createKey?: (index: number) => string,
): BatchDefectDraftRow[];
export function applyDefaultsToRows(
  rows: BatchDefectDraftRow[],
  defaults: BatchDefectDefaults,
  mode?: 'overwrite' | 'fillEmpty',
): BatchDefectDraftRow[];
export function validateBatchDefectRows(rows: BatchDefectDraftRow[]): {
  valid: boolean;
  errors: BugBatchRowError[];
  items: BugBatchCreateItem[];
};
export function extractServerRowErrors(errorBody: { meta?: Record<string, unknown> } | null | undefined): BugBatchRowError[];
