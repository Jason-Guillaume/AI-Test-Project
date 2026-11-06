export const DRAFT_LEAVE_MESSAGE: string;
export function createDraftNavigationController(
  target: Window & typeof globalThis, confirmLeave: (message: string) => boolean,
): { setHasDrafts(value: boolean): void; allowNextNavigation(): void; dispose(): void };
