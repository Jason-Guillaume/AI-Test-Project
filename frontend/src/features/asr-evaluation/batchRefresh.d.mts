export function shouldPollBatchSummary(jobStatus: string | undefined, summary: { review_active?: number; ab_active?: number } | undefined): boolean;
export function enteredTerminalJobState(previousStatus: string | undefined, currentStatus: string | undefined): boolean;
