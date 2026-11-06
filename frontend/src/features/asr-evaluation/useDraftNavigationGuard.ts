import { useEffect } from 'react';
import { createDraftNavigationController, DRAFT_LEAVE_MESSAGE } from './draftNavigationController.mjs';

let activeController: ReturnType<typeof createDraftNavigationController> | null = null;
let activeDrafts = false;

/** Call from the application entry before BrowserRouter is rendered. */
export function initializeDraftNavigationGuard() {
  if (typeof window === 'undefined' || activeController) return;
  activeController = createDraftNavigationController(window, (message) => window.confirm(message));
  activeController.setHasDrafts(activeDrafts);
}

/** Protect router links, navigate()/history changes, browser back/forward and reload/close. */
export function useDraftNavigationGuard(hasDrafts: boolean) {
  useEffect(() => {
    activeDrafts = hasDrafts;
    activeController?.setHasDrafts(hasDrafts);
    return () => {
      activeDrafts = false;
      activeController?.setHasDrafts(false);
    };
  }, [hasDrafts]);
}

export function confirmDraftDiscard(): boolean {
  const confirmed = window.confirm(DRAFT_LEAVE_MESSAGE);
  if (confirmed) activeController?.allowNextNavigation();
  return confirmed;
}
