export const PAGE_SIZE = 100;

export function splitCsv(text: string | undefined): string[] {
  return (text ?? '').split(',').map((s) => s.trim()).filter(Boolean);
}

export function joinCsv(list: string[] | undefined): string {
  return (list ?? []).join(', ');
}
