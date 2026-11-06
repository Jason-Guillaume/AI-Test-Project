export type ExperimentValue = string | number | boolean | null | ExperimentValue[] | { [key: string]: ExperimentValue };
export function experimentStatusLabel(status: string): string;
export function parameterDiffs(
  baseline: Record<string, ExperimentValue> | null | undefined,
  candidate: Record<string, ExperimentValue>,
  prefix?: string,
): Array<{ path: string; baseline: ExperimentValue | undefined; candidate: ExperimentValue | undefined }>;
export function parameterChangeSummary(
  baseline: Record<string, ExperimentValue> | null | undefined,
  candidate: Record<string, ExperimentValue>,
): string;
