export function clearMatchingReviewDraft(
  drafts: Record<number, string>, revisions: Record<number, number>,
  variables: { blockId: number; submittedText: string; submittedRevision: number; savesDraft?: boolean },
): Record<number, string>;
