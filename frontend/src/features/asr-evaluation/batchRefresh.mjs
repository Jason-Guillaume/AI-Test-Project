export function shouldPollBatchSummary(jobStatus, summary) {
  return ['QUEUED', 'RUNNING'].includes(jobStatus ?? '')
    || Boolean(summary?.review_active || summary?.ab_active);
}

export function enteredTerminalJobState(previousStatus, currentStatus) {
  return ['QUEUED', 'RUNNING'].includes(previousStatus ?? '')
    && !['QUEUED', 'RUNNING'].includes(currentStatus ?? '');
}
