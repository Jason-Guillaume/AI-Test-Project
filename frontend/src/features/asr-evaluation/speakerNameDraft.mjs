/** Keep speaker-name drafts only while they differ from the current persisted name. */
export function updateSpeakerNameDraft(drafts, speakerId, nextName, savedName) {
  const next = { ...drafts };
  if (nextName === savedName) delete next[speakerId];
  else next[speakerId] = nextName;
  return next;
}

export function clearSpeakerDrafts() {
  return {};
}
