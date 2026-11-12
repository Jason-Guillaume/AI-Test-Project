type FrozenRun = {
  id: number; connection_id: number; role: string; status: string;
  request_snapshot?: Record<string, unknown> | null;
};
type FrozenJobSnapshot = {
  connections?: Array<{ id: number; name?: string | null }>;
  model_slots?: Array<{ legacy_connection_id?: number | null; slot?: string | null }>;
} | null | undefined;
export function modelSwitchOption(
  run: FrozenRun,
  jobSnapshot: FrozenJobSnapshot,
  statusLabel: (status: string) => string,
): { value: number; label: string };
