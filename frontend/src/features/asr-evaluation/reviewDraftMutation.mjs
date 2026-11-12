/** Clear only the exact draft revision that a successful review request saved. */
export function clearMatchingReviewDraft(drafts, revisions, variables) {
  if (!variables.savesDraft) return drafts;
  const { blockId, submittedText, submittedRevision } = variables;
  if (drafts[blockId] !== submittedText || revisions[blockId] !== submittedRevision) return drafts;
  const next = { ...drafts };
  delete next[blockId];
  return next;
}
