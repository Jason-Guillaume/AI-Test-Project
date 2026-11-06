export const DRAFT_LEAVE_MESSAGE = '有未保存的人工修订草稿，离开后将丢失。仍要离开吗？';

/** Intercept router history writes and browser history traversal while preserving browser semantics. */
export function createDraftNavigationController(target, confirmLeave) {
  let hasDrafts = false;
  let lastIndex = Number.isInteger(target.history.state?.idx) ? target.history.state.idx : null;
  let restoringIndex = null;
  let skipNextPushPrompt = false;
  const originalPush = target.history.pushState.bind(target.history);
  const originalReplace = target.history.replaceState.bind(target.history);

  const pushState = (state, unused, url) => {
    const destination = url == null ? target.location.href : new URL(String(url), target.location.href).href;
    const bypass = skipNextPushPrompt;
    skipNextPushPrompt = false;
    if (!bypass && hasDrafts && destination !== target.location.href && !confirmLeave(DRAFT_LEAVE_MESSAGE)) return;
    originalPush(state, unused, url);
    const index = state?.idx;
    if (Number.isInteger(index)) lastIndex = index;
  };
  const replaceState = (state, unused, url) => {
    const destination = url == null ? target.location.href : new URL(String(url), target.location.href).href;
    const bypass = skipNextPushPrompt;
    skipNextPushPrompt = false;
    if (!bypass && hasDrafts && destination !== target.location.href && !confirmLeave(DRAFT_LEAVE_MESSAGE)) return;
    originalReplace(state, unused, url);
    const index = state?.idx;
    if (Number.isInteger(index)) lastIndex = index;
  };
  target.history.pushState = pushState;
  target.history.replaceState = replaceState;

  const onPopState = (event) => {
    const nextIndex = Number.isInteger(event.state?.idx) ? event.state.idx : null;
    if (restoringIndex !== null && nextIndex === restoringIndex) {
      lastIndex = nextIndex;
      restoringIndex = null;
      return;
    }
    if (!hasDrafts) {
      lastIndex = nextIndex;
      return;
    }
    if (confirmLeave(DRAFT_LEAVE_MESSAGE)) {
      lastIndex = nextIndex;
      return;
    }
    event.preventDefault();
    event.stopImmediatePropagation();
    if (nextIndex !== null && lastIndex !== null && nextIndex !== lastIndex) {
      restoringIndex = lastIndex;
      target.history.go(lastIndex - nextIndex);
    }
  };
  const beforeUnload = (event) => {
    if (!hasDrafts) return;
    event.preventDefault();
    event.returnValue = '';
  };
  target.addEventListener('popstate', onPopState, true);
  target.addEventListener('beforeunload', beforeUnload);

  return {
    setHasDrafts(value) { hasDrafts = value; },
    allowNextNavigation() { skipNextPushPrompt = true; },
    dispose() {
      target.removeEventListener('popstate', onPopState, true);
      target.removeEventListener('beforeunload', beforeUnload);
      target.history.pushState = originalPush;
      target.history.replaceState = originalReplace;
    },
  };
}
